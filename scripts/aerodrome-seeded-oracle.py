#!/usr/bin/env python3
"""Early-history, hermetic Oracle seed integration; never production admission.

The owned PostgreSQL database is reconstructed from pinned Graph Node-layout
CSV history. Its registry/health metadata is SYNTHETIC, not a production capture.
Fresh native subprocesses alone produce replay inputs; archived frames are only
comparison references. Existing artifacts and failed attempts are never replaced.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess

BUNDLE = Path('/private/tmp/aerodrome-producer-runtime-proof-v1/bundle')
ENGINE = Path('/Users/denis/Github/.worktrees/aerodrome-engine-supervised-proof')
CAPTURE = Path('/Users/denis/Github/.worktrees/aerodrome-engine-seed-capture')
REF = Path('/private/tmp/aerodrome-engine-segments-reference-v2')
ENCODING = Path('/private/tmp/aerodrome-reference-encoding-v1')
SQL = Path('/private/tmp/aerodrome-reference-sql-v3')
LAYOUT = Path('/private/tmp/aero-layout-proof-v1')
PG = Path('/opt/homebrew/opt/postgresql@16/bin')
NATIVE = Path('/private/tmp/aerodrome-live-wasm-m2-upgrade-v1/bin/substreams-native')
PROFILE = Path('/private/tmp/aerodrome-formal-root-v1/profile.json')
REPORTS = Path('/private/tmp/aerodrome-in-band-oracle-20261021-v2')
START, STOP = 13843704, 13919663
PARENT = '6c2f61721e0cab3cc3543828a6cf7bd0965d69bd974dccdec557007c97023d16'
PINS = {
 BUNDLE/'runtime.json':'5b976e577fd39b0c758c5ec155a768f2aac83e63a9a906de5251ca8f484487e9',
 BUNDLE/'bin/producer':'72190238b26b69ee901473bb3e21770a8d2efbd292f4b08147861f90a9f5a6eb',
 BUNDLE/'contract/block-changes-descriptor.json':'462d4f6d5222bf45c4912a6251bf473a55ddf49dc3a74e9acc252ee142a25638',
 BUNDLE/'spkg/extractor.spkg':'7df52603a63b261ed27faf5f27a0b178b2004e156829c6c0edc1b3d605b4ff59',
 NATIVE:'0788ff70a923004be0c4060a0a7d3c23ef4707e23fd089dc6d8d7bafb3871876',
 CAPTURE/'target/release/generic-seed-capture':'fbcdaa27185a6eaca18c3006ef35cf414ff7d31c46bafffd8b715ad01f4bca54',
 ENGINE/'scripts/aerodrome-host-supervisor.py':'4ae5de9b785f69e65b43d445f6fe1b06683becf656729f2ee6b2da755469b460',
 PROFILE:'6d38b3a9598e29ed3e65c2912c391de1f76e2454ecf0d4a97a9f09045c0be343',
 REF/'reference-plan.json':'431b4672473b17c184aac1400471f46038b77f3bfda3db8cb951caee11172c70',
 ENCODING/'encoding-complete.json':'1890024ab4fee381caf036ca28a266bb5f7adc841fe8e5661e39312d39cefae0',
 SQL/'complete.json':'51dc6f7103bb1e6c31e1566e2fafa9aea97605712107038dd4b8fedc3dc71a92',
 LAYOUT/'schema.graphql':'09d7c40167fc27c3aa2de0ec003fe7b0b469e132943cc26dcd4db6064769d0e8',
 LAYOUT/'deployment.yaml':'d93714e7ba268a91278f5c7c6a5b4ef71920d13b7e8d517f3542fb4a2edf6b20',
 LAYOUT/'layout.sql':'64b5983e2c43578d7c3b97e2156f01bb495e6f12686cc14deafa63a0b0b0f1d1',
 LAYOUT/'data-sources.sql':'79ef10bacd119708e24f92a5e488301204a68d4ea67f0ab3f5ed29ebf1fbcb5c',
 REPORTS/'r0.report.jsonl':'acff3061add1f1ee1b9000c65a459aee0be322e7f9e9eb6ac1ef62019ee21f89',
 REPORTS/'r1.report.jsonl':'21b29cd6b092e48cf80b93a5fe6be2825e182c56d2a0ea78ea8c9f5c960e8f91',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def pin(path):
    require(path.is_file() and not path.is_symlink(), f'not a regular input: {path}')
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return {'bytes': path.stat().st_size, 'sha256': digest}


def save(path, data):
    with path.open('xb') as f:
        f.write(data if isinstance(data, bytes) else canonical(data))
        f.flush()
        os.fsync(f.fileno())


def sealed(path, value):
    partial = path.with_name(path.name + '.partial')
    require(not path.exists(), 'completion already exists')
    save(partial, value)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
        # Hard link is atomic and refuses replacement, including a racing writer.
        os.link(partial, path)
        partial.unlink()
        os.fsync(fd)
    finally:
        os.close(fd)


def load(path):
    return json.loads(path.read_bytes())


def env():
    return {k: os.environ[k] for k in ('PATH','TMPDIR','TMP','TEMP','LANG','LC_ALL','LC_CTYPE') if k in os.environ}


def run(argv, directory, label, environment=None, stdin=None):
    with (directory/(label+'.stdout')).open('xb') as out, (directory/(label+'.stderr')).open('xb') as err:
        p = subprocess.run([str(x) for x in argv], input=stdin, stdout=out, stderr=err,
                           env=env() if environment is None else environment, check=False)
    save(directory/(label+'.exit.json'), {'exit_code':p.returncode})
    require(p.returncode == 0, f'{label} failed (retained logs)')
    return (directory/(label+'.stdout')).read_bytes()


def windows():
    starts = [n for n in range(13899663, STOP, 1000) if n != 13902663] + [13908827]
    return [{'from':s, 'stop_exclusive':s+1000} for s in sorted(starts)]


def reports():
    next_block, previous, counts, selected = START, PARENT, collections.Counter(), {}
    for name in ('r0.report.jsonl', 'r1.report.jsonl'):
        with (REPORTS/name).open() as f:
            header = json.loads(next(f))
            require(header['from'] == next_block, 'oracle report range discontinuity')
            for line in f:
                if not line.strip():
                    continue
                b = json.loads(line)
                require(b['number']==next_block and b['parent_hash'].removeprefix('0x')==previous,
                        'oracle report discontinuity')
                require(not b['deterministic_errors'] and not b['block_discarded'], 'unhealthy oracle report')
                hs = collections.Counter()
                for group in b['handler_groups']:
                    for h in group['handlers']:
                        require(h['outcome']=='ok', 'non-successful oracle handler')
                        hs[h['handler']] += 1
                counts.update(hs)
                previous = b['hash'].removeprefix('0x')
                selected[next_block] = {'number':next_block, 'hash':previous,
                    'parent_hash':b['parent_hash'].removeprefix('0x'), 'timestamp':b['timestamp'],
                    'triggered':b['mapping_triggered'], 'handlers':dict(hs), 'poi':b.get('poi'),
                    'created_data_sources':b['created_data_sources']}
                next_block += 1
    require(next_block == STOP, 'oracle report EOF before requested range')
    return selected, counts


def prepare(root):
    root.mkdir()
    allpins = {}
    for path, expected in PINS.items():
        observed = pin(path)
        require(observed['sha256']==expected, f'fixed input pin differs: {path}')
        allpins[str(path)] = observed
    # Freeze every runtime file, generated SQL, inventory, and referenced CSV.
    for path in sorted(BUNDLE.rglob('*')):
        if path.is_file():
            allpins[str(path)] = pin(path)
    for ordinal in range(3):
        for name in (f'segment-{ordinal}.sql', f'segment-{ordinal}.stdout.jsonl'):
            path=SQL/name; allpins[str(path)]=pin(path)
        directory=ENCODING/f'segment-{ordinal}'
        inventory=directory/'inventory.json'; allpins[str(inventory)]=pin(inventory)
        for table in load(inventory)['tables']:
            for kind in ('rows','clamps'):
                entry=table.get(kind)
                if entry is None:
                    continue
                path=directory/'rows'/entry['file']; observed=pin(path)
                require(observed=={k:entry[k] for k in ('bytes','sha256')}, 'CSV pin differs')
                allpins[str(path)]=observed
    reference=load(REF/'reference-plan.json')
    for ordinal, segment in enumerate(reference['segments']):
        for name, expected in segment['artifacts'].items():
            path=REF/f'segment-{ordinal}'/name
            require(pin(path)==expected, 'reference pin differs')
            allpins[str(path)]=expected
    allpins[str(CAPTURE/'fixtures/seed-capture/metadata-provenance.json')]=pin(CAPTURE/'fixtures/seed-capture/metadata-provenance.json')
    blocks, counts=reports()
    selected=windows()
    for w in selected:
        w['expected_parent_hash']=blocks[w['from']]['parent_hash']
        w['head_hash']=blocks[w['stop_exclusive']-1]['hash']
        c=collections.Counter()
        for n in range(w['from'],w['stop_exclusive']): c.update(blocks[n]['handlers'])
        w['handlers']=dict(c)
        w['triggered_blocks']=sum(blocks[n]['triggered'] for n in range(w['from'],w['stop_exclusive']))
    save(root/'input-pins.json', {'format':'pinax.aerodrome.hermetic-seeded-inputs/v1',
        'source_script':pin(Path(__file__).resolve()),'production_qualified':False,
        'synthetic_metadata':True,'pins':allpins,'windows':selected,
        'full_root_reports':{'from':START,'stop_exclusive':STOP,'handlers':dict(counts)},
        'limitation':'Early-history integration only; no Flash, no stratified M4 or production admission.'})
    save(root/'oracle-blocks.json', blocks)
    (root/'references').mkdir()
    for i,w in enumerate(selected):
        save(root/'references'/f'{i:02}.report.json', [blocks[n] for n in range(w['from'],w['stop_exclusive'])])
    print('Pinned inputs and 20 early-history windows', flush=True)


def check(root):
    manifest=load(root/'input-pins.json')
    for path, expected in manifest['pins'].items():
        require(pin(Path(path))==expected, f'input changed: {path}')
    return manifest


def pg_env(root):
    return {**env(),'PGHOST':str(root/'socket'),'PGPORT':'56223','PGUSER':'capture','PGDATABASE':'postgres'}


def sql(root, text, label):
    guard=f"DO $guard$ BEGIN IF current_setting('data_directory') <> '{root}/pgdata' OR current_database() <> 'postgres' THEN RAISE EXCEPTION 'wrong owned fixture'; END IF; END $guard$;\n"
    return run([PG/'psql','-X','-qAt','-v','ON_ERROR_STOP=1'],root,label,pg_env(root),(guard+text).encode())


def database(root):
    check(root)
    require(re.fullmatch(r'/private/tmp/[A-Za-z0-9_./-]+',str(root)), 'owned root must be safe /private/tmp path')
    (root/'socket').mkdir()
    run([PG/'initdb','-A','trust','-U','capture','--no-locale','--encoding=UTF8','-D',root/'pgdata'],root,'initdb')
    run([PG/'pg_ctl','-D',root/'pgdata','-l',root/'postgres.log','-o',f"-k {root}/socket -p 56223 -c listen_addresses='' -c fsync=on",'start'],root,'start')
    layout='CREATE EXTENSION btree_gist; CREATE SCHEMA sgd42;\n'+(LAYOUT/'layout.sql').read_text()+'\n'+(LAYOUT/'data-sources.sql').read_text()
    sql(root,layout.replace('sgd0','sgd42'),'layout')
    for ordinal in range(3):
        source=(SQL/f'segment-{ordinal}.sql').read_text()
        require(str(LAYOUT/'pgdata') in source, 'missing original DB guard')
        source=source.replace(str(LAYOUT/'pgdata'),str(root/'pgdata')).replace('sgd0','sgd42')
        save(root/f'load-{ordinal}.sql',source.encode())
        observed=run([PG/'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-f',root/f'load-{ordinal}.sql'],root,f'load-{ordinal}',pg_env(root))
        require(observed==(SQL/f'segment-{ordinal}.stdout.jsonl').read_bytes(),'reconstructed SQL history differs')
    profile=load(PROFILE)
    schema=(LAYOUT/'schema.graphql').read_text().replace("'","''")
    yaml=(LAYOUT/'deployment.yaml').read_text().replace("'","''")
    dep=profile['deployment']['deployment']
    tables=[t['physical_table'] for t in profile['tables'] if t['role']=='entity']
    metadata='''CREATE SCHEMA subgraphs;
CREATE TABLE subgraphs.deployment(id integer PRIMARY KEY,subgraph text,health text,failed boolean,fatal_error text,non_fatal_errors text[],graft_base text,graft_block_number integer,graft_block_hash bytea,earliest_block_number integer,current_reorg_depth integer,postponed_indexes_created boolean);
CREATE TABLE subgraphs.head(id integer PRIMARY KEY,block_number integer,block_hash bytea,entity_count bigint);
CREATE TABLE subgraphs.subgraph_manifest(id integer PRIMARY KEY,spec_version text,start_block_number integer,start_block_hash bytea,history_blocks integer,schema text,raw_yaml text,graph_node_version_id integer);
CREATE TABLE subgraphs.graph_node_versions(id integer PRIMARY KEY,crate_version text,git_commit_hash text);
CREATE TABLE subgraphs.subgraph_error(subgraph_id text);
CREATE TABLE subgraphs.table_stats(deployment integer,table_name text,last_pruned_block integer);
'''
    count=' + '.join(f'(SELECT count(*) FROM sgd42."{t}" WHERE block_range @> {STOP-1})' for t in tables + ['poi2$'])
    # Every selected schema entity is mutable in this exact Aerodrome profile.
    require(all(t['layout']=='mutable_block_range' for t in profile['tables'] if t['role']=='entity'),'unexpected entity layout')
    head=load(root/'oracle-blocks.json')[str(STOP-1)]['hash']
    metadata+=f"INSERT INTO subgraphs.deployment VALUES(42,'{dep}','healthy',false,NULL,'{{}}',NULL,NULL,NULL,{START-1},0,true);\n"
    metadata+=f"INSERT INTO subgraphs.head VALUES(42,{STOP-1},decode('{head}','hex'),{count});\n"
    metadata+=f"INSERT INTO subgraphs.subgraph_manifest VALUES(42,'1.2.0',{START-1},decode('{PARENT}','hex'),2147483647,'{schema}','{yaml}',1);\n"
    metadata+="INSERT INTO subgraphs.graph_node_versions VALUES(1,'0.44.0','77823b5a7adc4eac4abf03202c8dd7cb00dea31d');\n"
    metadata+=''.join(f"INSERT INTO subgraphs.table_stats VALUES(42,'{t}',NULL);\n" for t in tables)
    save(root/'synthetic-metadata.sql',metadata.encode())
    sql(root,'BEGIN;\n'+metadata+'COMMIT;','metadata')
    system=sql(root,'SELECT system_identifier::text FROM pg_control_system();','system-id').decode().strip()
    sealed(root/'database-complete.json', {'system_identifier':system,'site_id':42,'schema':'sgd42',
        'database':'postgres','synthetic_metadata':True,'production_qualified':False,
        'scope':'Exact root-derived entity/source/PoI histories; synthetic minimal GN metadata, not deployed registry/health/creator evidence.',
        'metadata_sql':pin(root/'synthetic-metadata.sql'),'source_input_pins':pin(root/'input-pins.json')})


def capture(root):
    check(root)
    db=load(root/'database-complete.json'); descriptor=load(BUNDLE/'contract/block-changes-descriptor.json')
    profile=load(PROFILE); blocks=load(root/'oracle-blocks.json'); (root/'seeds-v3').mkdir()
    descriptor_path=root/'capture-descriptor.json'
    if not descriptor_path.exists():
        save(descriptor_path,(BUNDLE/'contract/block-changes-descriptor.json').read_bytes())
        save(root/'capture-descriptor.sha256',(PINS[BUNDLE/'contract/block-changes-descriptor.json']+'\n').encode())
    require(pin(descriptor_path)['sha256']==PINS[BUNDLE/'contract/block-changes-descriptor.json'],'capture descriptor differs')
    executable=Path('/Users/denis/Github/.worktrees/aerodrome-engine-seed-zero-encoding/target/release/generic-seed-capture')
    executable_pin=pin(executable)
    require(executable_pin['sha256']=='5a8920cd020369bc5d95ea46812f506cd607cb786fa59d8ec6d3f963c8bda3ba','zero-fix executable pin differs')
    save(root/'capture-successor-v3.json',{'path':str(executable),'pin':executable_pin,'previous_capture':PINS[CAPTURE/'target/release/generic-seed-capture'],'reason':'Canonical zero encoding fix; prior failed populated capture retained.','production_qualified':False})
    retention=hashlib.sha256(json.dumps(descriptor['entity_retention'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    binding={'snapshot':{'deployment':descriptor['deployment'],'network':'base',
        'descriptor_sha256':PINS[BUNDLE/'contract/block-changes-descriptor.json'], 'retention_sha256':retention,
        'type_ordinals':descriptor['storage_profile']['entity_types'],'entity_id_policy':'string-only'},
        'purpose':'oracle','boundary':None,'start_block':START,
        'target':{k:db[k] for k in ('schema','site_id','database','system_identifier')},
        'profile_sha256':PINS[PROFILE],'catalog_sha256':profile['catalog']['sha256'],
        'schema_sha256':PINS[LAYOUT/'schema.graphql'],'raw_manifest_sha256':PINS[LAYOUT/'deployment.yaml'],
        'capture_binary_sha256':executable_pin['sha256'],
        'creating_graph_node':{'version':'0.44.0','commit':'77823b5a7adc4eac4abf03202c8dd7cb00dea31d'},
        'spec_version':'1.2.0','manifest_graft':None,'landing_graft':None}
    for b in sorted({w[k]-1 for w in windows() for k in ('from','stop_exclusive')}):
        binding['boundary']={'block_number':b,'block_hash':list(bytes.fromhex(blocks[str(b)]['hash']))}
        directory=root/'seeds-v3'/str(b); directory.mkdir(); save(directory/'binding.json',binding)
        run([executable,'oracle','--descriptor',root/'capture-descriptor.json',
            '--physical-profile',PROFILE,'--binding',directory/'binding.json','--binding-sha256',pin(directory/'binding.json')['sha256'],
            '--output',directory/'snapshot.bcgsnap','--allow-test-only'],directory,'capture',pg_env(root))
        snap=pin(directory/'snapshot.bcgsnap'); manifest=pin(directory/'snapshot.json')
        lineage=hashlib.sha256(b'pinax.generic-state-lineage/v1\0'+bytes(32)+bytes.fromhex(snap['sha256'])).digest()
        save(directory/'producer-pins.json',{'seed_manifest_sha256':list(bytes.fromhex(manifest['sha256'])),
             'capture_binding':binding,'engine_lineage':list(lineage)})
        print(f'Captured Oracle boundary {b}',flush=True)
    sealed(root/'captures-complete.json',{'boundaries':sorted(int(p.name) for p in (root/'seeds-v3').iterdir()),'production_qualified':False})


def live(root, ordinal):
    manifest=check(root); w=manifest['windows'][ordinal]; before_dir=root/'seeds-v3'/str(w['from']-1)
    attempt=root/f'window-{ordinal:02}-v3'; attempt.mkdir()
    base=[str(BUNDLE/'bin/producer'),'--runtime-sha256',PINS[BUNDLE/'runtime.json'],'--allow-non-final']
    seeded=json.loads(run(base+['seed','--from',str(before_dir/'snapshot.bcgsnap'),'--seed-manifest',str(before_dir/'snapshot.json'),
        '--seed-pins',str(before_dir/'producer-pins.json'),'--out',str(attempt/'state')],attempt,'seed'))
    require(seeded['capture_manifest_verified'] and not seeded['production_selectable'],'invalid seed import result')
    before=json.loads(run(base+['inspect','--state-dir',str(attempt/'state')],attempt,'inspect'))
    require(before==seeded['checkpoint'],'seed and reopened checkpoint differ')
    spec=importlib.util.spec_from_file_location('frozen_supervisor',ENGINE/'scripts/aerodrome-host-supervisor.py')
    supervisor=importlib.util.module_from_spec(spec); spec.loader.exec_module(supervisor)
    supervisor.segment_run(attempt,0,w,before,base,NATIVE,pin(NATIVE),BUNDLE,900,None)
    print(f'Fresh native and producer completed window {ordinal}',flush=True)


def reference_windows(root):
    manifest=check(root)
    outputs=[]
    try:
        for i,w in enumerate(manifest['windows']):
            outputs.append((w,(root/'references'/f'{i:02}.bcf1').open('xb')))
        for ordinal in range(3):
            with (REF/f'segment-{ordinal}'/'oracle-expected.bcf1').open('rb') as f:
                while header:=f.read(52):
                    require(len(header)==52 and header[:8]==b'BCF1\x01\0\0\0','bad reference clock')
                    n=struct.unpack('>Q',header[8:16])[0];size=struct.unpack('>I',header[48:52])[0]
                    require(size<=256*1024*1024,'oversized frame')
                    payload=f.read(size);require(len(payload)==size,'truncated reference')
                    for w,out in outputs:
                        if w['from']<=n<w['stop_exclusive']:out.write(header+payload)
        for _,out in outputs:out.flush();os.fsync(out.fileno())
    finally:
        for _,out in outputs:out.close()
    sealed(root/'references-complete.json',{'files':{f'{i:02}.bcf1':pin(root/'references'/f'{i:02}.bcf1') for i in range(20)},'reference_only':True})


def comparison_plan(root,ordinal):
    w=load(root/'input-pins.json')['windows'][ordinal]
    attempt=root/f'window-{ordinal:02}-v3'
    checkpoint=load(attempt/'segment-0'/'producer'/'complete.json')['checkpoint_sha256']
    pathpin=lambda p:{'path':str(p),'sha256':pin(p)['sha256']}
    before=root/'seeds-v3'/str(w['from']-1)
    after=root/'seeds-v3'/str(w['stop_exclusive']-1)
    plan={'descriptor':pathpin(root/'capture-descriptor.json'),
          'binding':load(before/'binding.json')['snapshot'],
          'before':pathpin(before/'snapshot.bcgsnap'),'after':pathpin(after/'snapshot.bcgsnap'),
          'frames':pathpin(attempt/'segment-0'/'frames.bcf1'),
          'reference_frames':pathpin(root/'references'/f'{ordinal:02}.bcf1'),
          'oracle_report':pathpin(root/'references'/f'{ordinal:02}.report.json'),
          'producer_state':str(attempt/'state'),
          'producer_checkpoint':pathpin(attempt/'state'/'checkpoints'/f'{checkpoint}.json')}
    save(attempt/'comparison-plan.json',plan)


def validate_result(window, plan_sha256, result):
    require(result.get('format')=='pinax.aerodrome.hermetic-oracle-comparison/v1'
        and result.get('plan_sha256')==plan_sha256
        and result.get('from')==window['from'] and result.get('stop_exclusive')==window['stop_exclusive']
        and result.get('blocks')==window['stop_exclusive']-window['from']
        and all(result.get(k) is True for k in ('full_producer_cache_matches','every_triggered_block_poi_matches','final_sql_visible_state_matches'))
        and result.get('whole_envelope_mask')==['compatibility_id']
        and result.get('loadable') is False and result.get('production_qualified') is False,
        'comparison result does not bind this exact plan/window/scope')


def verify_attempt(attempt, window, result):
    plan_path=attempt/'comparison-plan.json';plan=load(plan_path)
    for key in ('descriptor','before','after','frames','reference_frames','oracle_report','producer_checkpoint'):
        require(pin(Path(plan[key]['path']))['sha256']==plan[key]['sha256'],f'comparison input changed: {key}')
    require(Path(plan['producer_state'])==attempt/'state','producer state path differs')
    host=load(attempt/'segment-0'/'host-complete.json')
    require(host.get('format')=='pinax.aerodrome.development-host-segment/v1'
        and all(type(host.get(k)) is int and host[k]==0 for k in ('native_exit_code','producer_exit_code'))
        and all(host.get(k) is False for k in ('producer_receipt_v2','spool_READY','durable_engine_commit','production_qualified')),
        'host completion lacks actual successful exits or changes scope')
    for key,name in (('extractor','extractor.bcf1'),('frames','frames.bcf1'),('upstream_completion','sent-upstream-completion.json')):
        require(pin(attempt/'segment-0'/name)==host[key],f'host evidence changed: {key}')
    require(pin(Path(plan['producer_checkpoint']['path']))==host['checkpoint'],'host checkpoint differs')
    completion=load(attempt/'segment-0'/'sent-upstream-completion.json');request=completion['request']
    require(request['from']==window['from'] and request['stop_exclusive']==window['stop_exclusive']
        and request['observed_parent_hash']==window['expected_parent_hash']
        and completion['head']['block_number']==window['stop_exclusive']-1
        and bytes(completion['head']['block_hash']).hex()==window['head_hash']
        and completion['native_exit_code']==0
        and completion['input_sha256']==host['extractor']['sha256']
        and completion['input_bytes']==host['extractor']['bytes'], 'actual upstream completion differs from requested window')
    observed=load(result);validate_result(window,pin(plan_path)['sha256'],observed)
    return observed


def recheck(root):
    manifest=check(root);directory=root/'reviewed-comparisons';directory.mkdir()
    source=Path('/Users/denis/Github/.worktrees/aerodrome-seeded-oracle-helper/examples/aerodrome-oracle-comparison.rs')
    binary=Path('/Users/denis/Github/.worktrees/aerodrome-engine-supervised-proof/target/release/examples/aerodrome-oracle-comparison')
    helper=directory/'aerodrome-oracle-comparison';save(helper,binary.read_bytes());helper.chmod(0o755)
    save(directory/'aerodrome-oracle-comparison.rs',source.read_bytes())
    save(directory/'aerodrome-seeded-oracle.py',Path(__file__).read_bytes())
    save(directory/'identity.json',{'binary':pin(helper),'helper_source':pin(source),'harness_source':pin(Path(__file__)),
        'base_engine_commit':'e4580444c56d6fcc778cb50394a9a693823457eb',
        'changed_compile_inputs':{name:pin(source.parents[1]/name) for name in ('Cargo.toml','Cargo.lock','adapters/uniswap-v4-base/block-changes-v1.json','adapters/uniswap-v4-base/block-changes-v1.sha256')},
        'production_qualified':False})
    results=[]
    for i,w in enumerate(manifest['windows']):
        attempt=root/f'window-{i:02}-v3';plan=attempt/'comparison-plan.json';result=directory/f'{i:02}.json'
        verify_attempt(attempt,w,attempt/'comparison.json')
        run([helper,plan,result],directory,f'compare-{i:02}')
        observed=verify_attempt(attempt,w,result)
        results.append({'ordinal':i,'from':w['from'],'stop_exclusive':w['stop_exclusive'],'comparison':pin(result),
            'host':pin(attempt/'segment-0'/'host-complete.json'),'producer_redb':pin(attempt/'state'/'state.redb'),
            'operations':observed['operations'],'triggered_blocks':observed['triggered_blocks']})
    sealed(directory/'complete.json',{'format':'pinax.aerodrome.reviewed-hermetic-seeded-proof/v1','windows':results,
        'actual_live_attempts':pin(root/'twenty-windows-complete.json'),'identity':pin(directory/'identity.json'),
        'production_qualified':False,'loadable':False,'stratified_M4':False})
    print('All twenty existing actual live runs reverified with reviewed helper',flush=True)


def run_remaining(root):
    manifest=check(root)
    helper=Path('/Users/denis/Github/.worktrees/aerodrome-engine-supervised-proof/target/release/examples/aerodrome-oracle-comparison')
    # Freeze the built helper and source separately; it is a development
    # comparator, never an engine admission executable or production receipt.
    (root/'tools').mkdir()
    save(root/'tools'/'aerodrome-oracle-comparison',helper.read_bytes())
    helper=root/'tools'/'aerodrome-oracle-comparison';helper.chmod(0o755)
    source=Path('/Users/denis/Github/.worktrees/aerodrome-seeded-oracle-helper/examples/aerodrome-oracle-comparison.rs')
    save(root/'tools'/'aerodrome-oracle-comparison.rs',source.read_bytes())
    save(root/'tools'/'identity.json',{'binary':pin(helper),'source':pin(source),'base_commit':'e4580444c56d6fcc778cb50394a9a693823457eb','production_qualified':False})
    def one(i):
        attempt=root/f'window-{i:02}-v3'
        if not attempt.exists():
            live(root,i)
        else:
            require((attempt/'segment-0'/'host-complete.json').exists(), 'existing incomplete attempt must be retained, not retried')
        plan=attempt/'comparison-plan.json'
        if not plan.exists():comparison_plan(root,i)
        result=attempt/'comparison.json'
        if not result.exists():run([helper,plan,result],attempt,'compare')
        verify_attempt(attempt,manifest['windows'][i],result)
        print(f'Window {i}: exact frames, PoI, producer cache and SQL state verified',flush=True)
        return {'ordinal':i,'range':manifest['windows'][i],'host':pin(attempt/'segment-0'/'host-complete.json'),
                'comparison':pin(result),'checkpoint':pin(attempt/'state'/'checkpoints'/(load(attempt/'segment-0'/'producer'/'complete.json')['checkpoint_sha256']+'.json'))}
    results=[]
    # At most three disjoint reads. First failure stops queued work; every
    # running supervisor still owns/reaps its actual children and records facts.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures=[executor.submit(one,i) for i in range(20)]
        try:
            for future in concurrent.futures.as_completed(futures):results.append(future.result())
        except BaseException:
            for future in futures:future.cancel()
            raise
    sealed(root/'twenty-windows-complete.json',{'format':'pinax.aerodrome.hermetic-seeded-early-history/v1',
        'windows':sorted(results,key=lambda x:x['ordinal']),'actual_native_and_producer_exits':40,
        'requested_blocks':20000,'synthetic_metadata':True,'oracle_purpose_sticky':True,
        'production_qualified':False,'stratified_M4':False,'spool_READY':False,
        'comparison_helper':pin(root/'tools'/'identity.json'),'input_pins':pin(root/'input-pins.json'),
        'capture_successor':pin(root/'capture-successor-v3.json')})


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('command',choices=['prepare','database','capture','live','reference_windows','comparison_plan','run_remaining','recheck']);p.add_argument('root',type=Path);p.add_argument('--window',type=int)
    a=p.parse_args();root=a.root.absolute()
    if a.command in ('live','comparison_plan'):
        require(a.window is not None and 0<=a.window<20,'--window 0..19 required');globals()[a.command](root,a.window)
    else: globals()[a.command](root)

if __name__=='__main__': main()
