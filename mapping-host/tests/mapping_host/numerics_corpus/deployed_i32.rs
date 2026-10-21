//! Run the original, hash-pinned deployed ByteArray.toI32 implementation.
//! We add a test export without changing any function, data, or globals.
use super::{BigInt, Digest, OracleResult, Sha256};
use std::sync::{Mutex, OnceLock};
use wasmparser::{KnownCustom, Name, Parser, Payload};
use wasmtime::{Engine, ExternType, Instance, Linker, Memory, Module, Store, TypedFunc, Val};

pub const POOL_SHA256: &str = "778944cb5de130d35dd76718a2642a338e5637d1d3d58d5b64d7cdf096ed8272";
pub const METHOD: &str = "~lib/@graphprotocol/graph-ts/common/collections/ByteArray#toI32";

struct Machine {
    store: Store<i32>,
    memory: Memory,
    allocate: TypedFunc<(i32, i32), i32>,
    convert: TypedFunc<i32, i32>,
}

impl Machine {
    fn new() -> Self {
        let bytes =
            include_bytes!("../../../../aerodrome-slipstream-base/reference/mappings/Pool.wasm");
        assert_eq!(hex::encode(Sha256::digest(bytes)), POOL_SHA256);
        let mut function = None;
        for payload in Parser::new(0).parse_all(bytes) {
            if let Payload::CustomSection(section) = payload.unwrap() {
                if let KnownCustom::Name(names) = section.as_known() {
                    for subsection in names {
                        if let Name::Function(names) = subsection.unwrap() {
                            for name in names {
                                let name = name.unwrap();
                                if name.name == METHOD {
                                    assert!(function.replace(name.index).is_none());
                                }
                            }
                        }
                    }
                }
            }
        }
        let function = function.expect("deployed toI32 function name");
        let mut output = wasm_encoder::Module::new();
        for payload in Parser::new(0).parse_all(bytes) {
            let payload = payload.unwrap();
            if let Payload::ExportSection(exports) = payload {
                let mut section = wasm_encoder::ExportSection::new();
                for export in exports {
                    let export = export.unwrap();
                    let kind = match export.kind {
                        wasmparser::ExternalKind::Func => wasm_encoder::ExportKind::Func,
                        wasmparser::ExternalKind::Table => wasm_encoder::ExportKind::Table,
                        wasmparser::ExternalKind::Memory => wasm_encoder::ExportKind::Memory,
                        wasmparser::ExternalKind::Global => wasm_encoder::ExportKind::Global,
                        wasmparser::ExternalKind::Tag => wasm_encoder::ExportKind::Tag,
                    };
                    section.export(export.name, kind, export.index);
                }
                section.export("__test_to_i32", wasm_encoder::ExportKind::Func, function);
                output.section(&section);
            } else if let Some((id, range)) = payload.as_section() {
                output.section(&wasm_encoder::RawSection {
                    id,
                    data: &bytes[range],
                });
            }
        }
        let engine = Engine::default();
        let module = Module::new(&engine, output.finish()).unwrap();
        let mut store = Store::new(&engine, 0);
        let mut linker = Linker::new(&engine);
        for import in module.imports() {
            let ExternType::Func(ty) = import.ty() else {
                panic!("unexpected mapping import")
            };
            let name = import.name().to_owned();
            linker
                .func_new(
                    import.module(),
                    import.name(),
                    ty,
                    move |caller, _, results| {
                        if name == "typeConversion.bytesToHex" {
                            // Used only to construct the abort message. A valid empty
                            // string lets the original assertion reach env.abort.
                            results[0] = Val::I32(*caller.data());
                            Ok(())
                        } else if name == "abort" {
                            anyhow::bail!("deployed AssemblyScript assertion")
                        } else {
                            anyhow::bail!("unexpected import during toI32: {name}")
                        }
                    },
                )
                .unwrap();
        }
        let instance: Instance = linker.instantiate(&mut store, &module).unwrap();
        // No mapping initialization or handlers run. This pure method needs
        // only the original allocator and memory; all other imports trap.
        let memory = instance.get_memory(&mut store, "memory").unwrap();
        let allocate = instance
            .get_typed_func::<(i32, i32), i32>(&mut store, "__new")
            .unwrap();
        let empty = allocate.call(&mut store, (0, 2)).unwrap();
        *store.data_mut() = empty;
        let convert = instance
            .get_typed_func::<i32, i32>(&mut store, "__test_to_i32")
            .unwrap();
        Self {
            store,
            memory,
            allocate,
            convert,
        }
    }

    fn convert(&mut self, value: &BigInt) -> OracleResult<i32> {
        let bytes = value.to_signed_bytes_le();
        let buffer = self
            .allocate
            .call(&mut self.store, (bytes.len() as i32, 0))
            .unwrap();
        self.memory
            .write(&mut self.store, buffer as usize, &bytes)
            .unwrap();
        let array = self.allocate.call(&mut self.store, (12, 9)).unwrap();
        let header = [buffer, buffer, bytes.len() as i32]
            .map(i32::to_le_bytes)
            .concat();
        self.memory
            .write(&mut self.store, array as usize, &header)
            .unwrap();
        self.convert.call(&mut self.store, array).map_err(|error| {
            assert!(
                format!("{error:#}").contains("deployed AssemblyScript assertion"),
                "unexpected WASM trap: {error:#}"
            );
            "i32_overflow"
        })
    }
}

pub fn convert(value: &BigInt) -> OracleResult<i32> {
    static MACHINE: OnceLock<Mutex<Machine>> = OnceLock::new();
    MACHINE
        .get_or_init(|| Mutex::new(Machine::new()))
        .lock()
        .unwrap()
        .convert(value)
}
