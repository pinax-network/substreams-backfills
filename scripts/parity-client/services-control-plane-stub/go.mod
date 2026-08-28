module github.com/streamingfast/services-control-plane

go 1.26.0

// Intentionally package-less. The upstream v1.20.3 module graph names a
// private module, but the v1.20.3 RPC-v3 package closure used by this client
// does not import it. CI proves it never enters the runtime dependency graph.
