use aerodrome_slipstream_reducer::{identity::InputBinding,input::InputStream,reference::Cassette};
use aerodrome_extractor_audit as audit;
use aerodrome_extractor_core::config::{Config,PARAMS};
use backfill_common::descriptor::ExtractorIdentity;
use sha2::{Digest,Sha256};
use std::{collections::BTreeMap,io::{Read,BufReader},rc::Rc,cell::RefCell,fs};
type Result<T> = std::result::Result<T,Box<dyn std::error::Error>>;
struct HashReader<R>{input:R,digest:Rc<RefCell<Sha256>>}
impl<R:Read> Read for HashReader<R>{fn read(&mut self,b:&mut[u8])->std::io::Result<usize>{let n=self.input.read(b)?;self.digest.borrow_mut().update(&b[..n]);Ok(n)}}
fn hex(s:&str)->Result<Vec<u8>>{Ok(hex::decode(s.strip_prefix("0x").ok_or("hex prefix missing")?)?)}
fn main()->Result<()> {
 let args=std::env::args().skip(1).collect::<Vec<_>>();
 if args.first().is_some_and(|s|s=="--build-descriptor") {
  if args.len()!=4{return Err("usage: --build-descriptor EXTRACTOR_IDENTITY REDUCER_COMMIT OUTPUT".into())}
  let identity:ExtractorIdentity=serde_json::from_slice(&fs::read(&args[1])?)?;
  let bytes=aerodrome_slipstream_reducer::identity::build_descriptor(&identity,&args[2],true)?;
  use std::io::Write;
  let mut file=fs::OpenOptions::new().write(true).create_new(true).open(&args[3])?;
  file.write_all(&bytes)?;file.sync_all()?;
  println!("{}",hex::encode(Sha256::digest(bytes)));return Ok(())
 }
 if args.len()!=6{return Err("usage: INPUT INPUT_SHA256 CASSETTE DESCRIPTOR EXTRACTOR_IDENTITY DESCRIPTOR_SHA256".into())}
 let cassette_bytes=fs::read(&args[2])?;
 let validated=Cassette::from_json(&cassette_bytes)?;
 if validated.sha256()!="1dabafa49d6c0e7725fd0a0a76975c22db183931cf56a2c76f12b35060fc61e3"{return Err("cassette pin mismatch".into())}
 let document:serde_json::Value=serde_json::from_slice(&cassette_bytes)?;
 let mut by_block=BTreeMap::<u64,Vec<&serde_json::Value>>::new();
 for entry in document["entries"].as_array().ok_or("entries absent")? {
  let number=entry["block_number"].as_u64().ok_or("block number absent")?;
  if !(13843704..13919663).contains(&number){return Err("call outside requested full root range".into())}
  by_block.entry(number).or_default().push(entry);
 }
 let expected_calls:usize=by_block.values().map(Vec::len).sum();
 if expected_calls!=9394{return Err("cassette expected count differs".into())}
 let descriptor=fs::read(&args[3])?;
 let descriptor_sha:[u8;32]=Sha256::digest(&descriptor).into();
 if hex::encode(descriptor_sha)!=args[5]{return Err("descriptor pin differs".into())}
 let identity:ExtractorIdentity=serde_json::from_slice(&fs::read(&args[4])?)?;
 let binding=InputBinding::new(&descriptor,descriptor_sha,&identity)?;
 let f=fs::File::open(&args[0])?;if !f.metadata()?.is_file(){return Err("input not regular".into())}
 let digest=Rc::new(RefCell::new(Sha256::new()));
 let parent=hex::decode("6c2f61721e0cab3cc3543828a6cf7bd0965d69bd974dccdec557007c97023d16")?.try_into().unwrap();
 let mut input=InputStream::new(HashReader{input:BufReader::new(f),digest:Rc::clone(&digest)},binding,13843704,13919662,parent)?;
 let cfg=Config::parse(PARAMS)?;
 let(mut blocks,mut matched,mut missing,mut mismatched)=(0u64,0usize,0usize,0usize);
 let mut functions=BTreeMap::<String,usize>::new();let mut errors=vec![];
 while let Some(valid)=input.next_block()? {
  blocks+=1;let block=valid.block();
  let Some(entries)=by_block.remove(&block.number) else{continue};
  let checks=audit::checks(block,&cfg,false)?;
  for e in entries {
   if hex(e["block_hash"].as_str().unwrap())?!=block.hash{return Err("cassette/input block hash differs".into())}
   let address=hex(e["address"].as_str().unwrap())?;let calldata=hex(e["calldata"].as_str().unwrap())?;
   let function=format!("{}.{}",e["contract"].as_str().unwrap(),e["function"].as_str().unwrap());
   *functions.entry(function.clone()).or_default()+=1;
   let observed=checks.iter().find(|c|c.address.as_slice()==address&&c.calldata==calldata);
   let message=if let Some(c)=observed {
    let expected=match e["retval"]["kind"].as_str().unwrap(){"null"=>audit::Retval::Reverted,"value"=>audit::Retval::Value{data:hex::encode(hex(e["retval"]["data"].as_str().unwrap())?)},_=>unreachable!()};
    match audit::compare(c,&expected){Ok(())=>{matched+=1;None},Err(err)=>{mismatched+=1;Some(err)}}
   }else{missing+=1;Some("actual WASM frame has no answer for retained cassette call".into())};
   if let Some(message)=message{if errors.len()<100{errors.push(serde_json::json!({"block":block.number,"function":function,"address":e["address"],"calldata":e["calldata"],"error":message}));}}
  }
 }
 let head=input.finish()?;let observed=hex::encode(digest.borrow().clone().finalize());
 if observed!=args[1]||blocks!=75959||!by_block.is_empty(){return Err("input digest/range/cassette coverage differs".into())}
 let passed=missing==0&&mismatched==0&&matched==expected_calls;
 println!("{}",serde_json::to_string_pretty(&serde_json::json!({"schema":"aerodrome-live-wasm-full-cassette-audit/v1","passed":passed,"source_commit":"5e65aa2226dbcb42ae25e8784af989327967e1e6","binary_sha256":hex::encode(Sha256::digest(fs::read(std::env::current_exe()?)?)),"input_sha256":observed,"cassette_sha256":validated.sha256(),"descriptor_sha256":hex::encode(descriptor_sha),"extractor_identity":identity,"from":13843704,"to_exclusive":13919663,"blocks":blocks,"head_hash":hex::encode(head),"canonical_frames_and_eof_verified":true,"expected_calls":expected_calls,"matched_calls":matched,"missing_calls":missing,"mismatched_calls":mismatched,"functions":functions,"error_examples":errors,"comparison_masks":"unchanged existing archive auditor consumed fields; no supplemental answers"}))?);
 if !passed{std::process::exit(4)}
 Ok(())
}
