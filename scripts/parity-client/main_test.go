package main

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/streamingfast/bstream"
	pbsubstreamsrpc "github.com/streamingfast/substreams/pb/sf/substreams/rpc/v2"
	pbsubstreamsrpcv3 "github.com/streamingfast/substreams/pb/sf/substreams/rpc/v3"
	pbsubstreams "github.com/streamingfast/substreams/pb/sf/substreams/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/anypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func testBlockID(block uint64) string {
	return fmt.Sprintf("%064x", block)
}

func testCursor(block uint64, id string) string {
	ref := bstream.NewBlockRef(id, block)
	return (&bstream.Cursor{
		Step:      bstream.StepNewIrreversible,
		Block:     ref,
		HeadBlock: ref,
		LIB:       ref,
	}).ToOpaque()
}

func sessionResponse() *pbsubstreamsrpc.Response {
	return &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_Session{
		Session: &pbsubstreamsrpc.SessionInit{
			ResolvedStartBlock: startBlock,
		},
	}}
}

func blockResponse(block uint64, value []byte) *pbsubstreamsrpc.Response {
	id := testBlockID(block)
	return &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_BlockScopedData{
		BlockScopedData: &pbsubstreamsrpc.BlockScopedData{
			Output: &pbsubstreamsrpc.MapModuleOutput{
				Name: outputModule,
				MapOutput: &anypb.Any{
					TypeUrl: outputTypeURL,
					Value:   value,
				},
			},
			Clock: &pbsubstreams.Clock{
				Number:    block,
				Id:        id,
				Timestamp: timestamppb.New(time.Unix(int64(block), int64(block%1_000_000_000))),
			},
			Cursor:           testCursor(block, id),
			FinalBlockHeight: block,
		},
	}}
}

func initializedValidator(t *testing.T) (*streamValidator, *bytes.Buffer) {
	t.Helper()
	var output bytes.Buffer
	validator := newStreamValidator(&output)
	if err := validator.handle(sessionResponse()); err != nil {
		t.Fatalf("session failed: %v", err)
	}
	return validator, &output
}

func testBinding() invocationBinding {
	packageIdentity := artifactIdentity{SHA256: strings.Repeat("a", 64), Bytes: 100}
	request := contractFor(packageIdentity)
	requestSHA256, err := requestDigest(request)
	if err != nil {
		panic(err)
	}
	return invocationBinding{
		SessionID:          strings.Repeat("b", 64),
		InvocationID:       strings.Repeat("c", 64),
		Role:               "baseline",
		SourceRevision:     strings.Repeat("d", 40),
		Endpoint:           "localhost:443",
		AuthKind:           "x-api-key",
		Package:            packageIdentity,
		CaptureClient:      artifactIdentity{SHA256: strings.Repeat("e", 64), Bytes: 200},
		Request:            request,
		RequestSHA256:      requestSHA256,
		SanitizedArgv:      []string{"uniswap-v3-mainnet-parity-client"},
		StartedAtUnixNanos: time.Now().Add(-time.Second).UnixNano(),
	}
}

func TestCompleteStreamIncludesZeroByteOutputsAndCompletion(t *testing.T) {
	validator, output := initializedValidator(t)
	for block := startBlock; block < stopBlock; block++ {
		var value []byte
		if block%2 == 0 {
			value = []byte{0x2a, 0x00}
		}
		if err := validator.handle(blockResponse(block, value)); err != nil {
			t.Fatalf("block %d failed: %v", block, err)
		}
	}
	if err := validator.finish(testBinding()); err != nil {
		t.Fatalf("completion failed: %v", err)
	}
	lines := strings.Split(strings.TrimSuffix(output.String(), "\n"), "\n")
	if got, want := len(lines), int(blockCount)+1; got != want {
		t.Fatalf("line count %d, want %d", got, want)
	}
	var zero blockRecord
	if err := json.Unmarshal([]byte(lines[0]), &zero); err != nil {
		t.Fatal(err)
	}
	if zero.MapOutputBytes != 0 || zero.MapOutputBase64 != "" ||
		zero.MapOutputSHA256 != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" {
		t.Fatalf("zero-byte output was not explicit: %#v", zero)
	}
	var completion completionRecord
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &completion); err != nil {
		t.Fatal(err)
	}
	if !completion.Completed || completion.BlockCount != blockCount || completion.LastBlock != stopBlock-1 {
		t.Fatalf("invalid completion: %#v", completion)
	}
}

func TestEarlyEOFIsRejected(t *testing.T) {
	validator, _ := initializedValidator(t)
	for block := startBlock; block < stopBlock-1; block++ {
		if err := validator.handle(blockResponse(block, nil)); err != nil {
			t.Fatal(err)
		}
	}
	if err := validator.finish(testBinding()); err == nil {
		t.Fatal("truncated stream passed completion")
	}
}

func TestDuplicateMissingAndOutOfRangeBlocksAreRejected(t *testing.T) {
	tests := []struct {
		name  string
		block uint64
	}{
		{"duplicate", startBlock - 1},
		{"missing", startBlock + 1},
		{"out-of-range", stopBlock},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator, _ := initializedValidator(t)
			if err := validator.handle(blockResponse(test.block, nil)); err == nil {
				t.Fatalf("block %d was accepted", test.block)
			}
		})
	}
}

func TestSessionAndProgressSemantics(t *testing.T) {
	var output bytes.Buffer
	validator := newStreamValidator(&output)
	progress := &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_Progress{
		Progress: &pbsubstreamsrpc.ModulesProgress{},
	}}
	if err := validator.handle(progress); err == nil {
		t.Fatal("progress before session was accepted")
	}
	badSession := sessionResponse()
	badSession.GetSession().ResolvedStartBlock++
	if err := validator.handle(badSession); err == nil {
		t.Fatal("session with the wrong resolved start was accepted")
	}
	validator = newStreamValidator(&output)
	if err := validator.handle(sessionResponse()); err != nil {
		t.Fatal(err)
	}
	if err := validator.handle(progress); err != nil {
		t.Fatalf("progress after session was rejected: %v", err)
	}
	if err := validator.handle(sessionResponse()); err == nil {
		t.Fatal("duplicate session was accepted")
	}
	validator, _ = initializedValidator(t)
	for block := startBlock; block < stopBlock; block++ {
		if err := validator.handle(blockResponse(block, nil)); err != nil {
			t.Fatal(err)
		}
	}
	if err := validator.handle(progress); err != nil {
		t.Fatalf("final progress before EOF was rejected: %v", err)
	}
}

func TestUpstreamShapedSessionWithZeroChainHeadIsAccepted(t *testing.T) {
	response := sessionResponse()
	if response.GetSession().ChainHead != 0 {
		t.Fatal("fixture is not shaped like the pinned v1.20.3 SessionInit")
	}
	validator := newStreamValidator(io.Discard)
	if err := validator.handle(response); err != nil {
		t.Fatalf("upstream-shaped session was rejected: %v", err)
	}
}

func TestProgressRejectsMalformedNilAndWithoutSessionEnvelopes(t *testing.T) {
	progress := &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_Progress{
		Progress: &pbsubstreamsrpc.ModulesProgress{},
	}}
	tests := []struct {
		name      string
		validator *streamValidator
		response  *pbsubstreamsrpc.Response
	}{
		{"malformed-nil-response", newStreamValidator(io.Discard), nil},
		{"malformed-nil-message", newStreamValidator(io.Discard), &pbsubstreamsrpc.Response{}},
		{"nil-progress", func() *streamValidator {
			validator, _ := initializedValidator(t)
			return validator
		}(), &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_Progress{}}},
		{"progress-without-session", newStreamValidator(io.Discard), progress},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := test.validator.handle(test.response); err == nil {
				t.Fatal("invalid progress envelope was accepted")
			}
		})
	}
}

func TestForbiddenResponseKindsAreRejected(t *testing.T) {
	tests := []struct {
		name     string
		response *pbsubstreamsrpc.Response
	}{
		{"nil-response", nil},
		{"nil-oneof", &pbsubstreamsrpc.Response{}},
		{"nil-progress", &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_Progress{}}},
		{"undo", &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_BlockUndoSignal{BlockUndoSignal: &pbsubstreamsrpc.BlockUndoSignal{}}}},
		{"fatal", &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_FatalError{FatalError: &pbsubstreamsrpc.Error{}}}},
		{"snapshot", &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_DebugSnapshotData{DebugSnapshotData: &pbsubstreamsrpc.InitialSnapshotData{}}}},
		{"snapshot-complete", &pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_DebugSnapshotComplete{DebugSnapshotComplete: &pbsubstreamsrpc.InitialSnapshotComplete{}}}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator, _ := initializedValidator(t)
			if err := validator.handle(test.response); err == nil {
				t.Fatal("forbidden response was accepted")
			}
		})
	}
}

func TestMalformedBlockSemanticsAreRejected(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*pbsubstreamsrpc.BlockScopedData)
	}{
		{"nil-clock", func(data *pbsubstreamsrpc.BlockScopedData) { data.Clock = nil }},
		{"nil-output", func(data *pbsubstreamsrpc.BlockScopedData) { data.Output = nil }},
		{"nil-map-output", func(data *pbsubstreamsrpc.BlockScopedData) { data.Output.MapOutput = nil }},
		{"partial", func(data *pbsubstreamsrpc.BlockScopedData) { data.IsPartial = true }},
		{"partial-index", func(data *pbsubstreamsrpc.BlockScopedData) { value := uint32(1); data.PartialIndex = &value }},
		{"partial-last", func(data *pbsubstreamsrpc.BlockScopedData) { value := true; data.IsLastPartial = &value }},
		{"debug-map-output", func(data *pbsubstreamsrpc.BlockScopedData) {
			data.DebugMapOutputs = []*pbsubstreamsrpc.MapModuleOutput{{}}
		}},
		{"debug-store-output", func(data *pbsubstreamsrpc.BlockScopedData) {
			data.DebugStoreOutputs = []*pbsubstreamsrpc.StoreModuleOutput{{}}
		}},
		{"wrong-module", func(data *pbsubstreamsrpc.BlockScopedData) { data.Output.Name = "other" }},
		{"wrong-type", func(data *pbsubstreamsrpc.BlockScopedData) {
			data.Output.MapOutput.TypeUrl = "type.googleapis.com/other"
		}},
		{"uppercase-hash", func(data *pbsubstreamsrpc.BlockScopedData) { data.Clock.Id = strings.ToUpper(data.Clock.Id) }},
		{"wrong-final-height", func(data *pbsubstreamsrpc.BlockScopedData) { data.FinalBlockHeight-- }},
		{"nil-timestamp", func(data *pbsubstreamsrpc.BlockScopedData) { data.Clock.Timestamp = nil }},
		{"invalid-timestamp", func(data *pbsubstreamsrpc.BlockScopedData) {
			data.Clock.Timestamp = &timestamppb.Timestamp{Seconds: 253402300800}
		}},
		{"absent-cursor", func(data *pbsubstreamsrpc.BlockScopedData) { data.Cursor = "" }},
		{"foreign-cursor", func(data *pbsubstreamsrpc.BlockScopedData) {
			data.Cursor = testCursor(data.Clock.Number+1, testBlockID(data.Clock.Number+1))
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator, _ := initializedValidator(t)
			response := blockResponse(startBlock, nil)
			test.mutate(response.GetBlockScopedData())
			if err := validator.handle(response); err == nil {
				t.Fatal("malformed block was accepted")
			}
		})
	}
}

func TestRequestIsExactProtocolV3DevelopmentContract(t *testing.T) {
	pkg := &pbsubstreams.Package{}
	request := requestFor(pkg)
	if request.Package != pkg || request.StartBlockNum != int64(startBlock) ||
		request.StopBlockNum != stopBlock || !request.FinalBlocksOnly || request.ProductionMode ||
		request.OutputModule != outputModule || request.Network != "mainnet" || request.NoopMode ||
		request.LimitProcessedBlocks != blockCount || request.PartialBlocks || len(request.Params) != 0 ||
		len(request.DebugInitialStoreSnapshotForModules) != 0 ||
		len(request.DevOutputModules) != 1 || request.DevOutputModules[0] != outputModule {
		t.Fatalf("request contract drift: %#v", request)
	}
}

func TestPackageOutputContract(t *testing.T) {
	valid := &pbsubstreams.Package{
		Network: "mainnet",
		Modules: &pbsubstreams.Modules{Modules: []*pbsubstreams.Module{{
			Name: outputModule,
			Kind: &pbsubstreams.Module_KindMap_{KindMap: &pbsubstreams.Module_KindMap{
				OutputType: packageOutputType,
			}},
		}}},
	}
	if err := validatePackage(valid); err != nil {
		t.Fatalf("valid package failed: %v", err)
	}
	valid.Modules.Modules = append(valid.Modules.Modules, valid.Modules.Modules[0])
	if err := validatePackage(valid); err == nil {
		t.Fatal("duplicate graph_out module was accepted")
	}
}

func TestControlledBuildRealPackageContracts(t *testing.T) {
	value := os.Getenv("UNISWAP_V3_PARITY_REAL_PACKAGES")
	if value == "" {
		t.Skip("real controlled-build package paths are supplied by the reference job")
	}
	paths := filepath.SplitList(value)
	if len(paths) != 3 {
		t.Fatalf("expected baseline, mainnet, and Base package paths, got %d", len(paths))
	}
	for index, path := range paths {
		raw, _, err := fileIdentity(path, maxPackageBytes, "real controlled-build package")
		if err != nil {
			t.Fatal(err)
		}
		var pkg pbsubstreams.Package
		if err := proto.Unmarshal(raw, &pkg); err != nil {
			t.Fatal(err)
		}
		err = validatePackage(&pkg)
		if index < 2 && err != nil {
			t.Fatalf("mainnet package %s failed: %v", filepath.Base(path), err)
		}
		if index == 2 && err == nil {
			t.Fatal("Base package was accepted by the mainnet-only capture client")
		}
	}
}

func TestAuthorizationIsExactAndMutuallyExclusive(t *testing.T) {
	t.Setenv("SUBSTREAMS_API_KEY", "")
	t.Setenv("SUBSTREAMS_API_TOKEN", "")
	if _, _, err := authorization(); err == nil {
		t.Fatal("absent credentials were accepted")
	}
	t.Setenv("SUBSTREAMS_API_KEY", "api-key-value")
	auth, kind, err := authorization()
	if err != nil {
		t.Fatal(err)
	}
	metadata, err := auth.GetRequestMetadata(context.Background())
	if err != nil || kind != "x-api-key" || metadata["x-api-key"] != "api-key-value" || !auth.RequireTransportSecurity() {
		t.Fatalf("API key auth drift: %#v, %v", metadata, err)
	}
	t.Setenv("SUBSTREAMS_API_TOKEN", "token-value")
	if _, _, err := authorization(); err == nil {
		t.Fatal("simultaneous credentials were accepted")
	}
	t.Setenv("SUBSTREAMS_API_KEY", "")
	auth, kind, err = authorization()
	if err != nil {
		t.Fatal(err)
	}
	metadata, err = auth.GetRequestMetadata(context.Background())
	if err != nil || kind != "bearer-token" || metadata["authorization"] != "Bearer token-value" || !auth.RequireTransportSecurity() {
		t.Fatalf("token auth drift: %#v, %v", metadata, err)
	}
}

type shortWriter struct{}

func (shortWriter) Write(value []byte) (int, error) {
	if len(value) == 0 {
		return 0, nil
	}
	return len(value) - 1, nil
}

func TestShortWritesAreRejected(t *testing.T) {
	validator := newStreamValidator(shortWriter{})
	if err := validator.handle(sessionResponse()); err != nil {
		t.Fatal(err)
	}
	if err := validator.handle(blockResponse(startBlock, nil)); err == nil {
		t.Fatal("short block-record write passed")
	}

	validator, _ = initializedValidator(t)
	for block := startBlock; block < stopBlock; block++ {
		if err := validator.handle(blockResponse(block, nil)); err != nil {
			t.Fatal(err)
		}
	}
	validator.w = shortWriter{}
	if err := validator.finish(testBinding()); err == nil {
		t.Fatal("short completion-record write passed")
	}
}

func TestCursorStepAndLIBMustBindFinalBlock(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*bstream.Cursor)
	}{
		{"non-final-step", func(cursor *bstream.Cursor) { cursor.Step = bstream.StepNew }},
		{"foreign-lib", func(cursor *bstream.Cursor) {
			cursor.LIB = bstream.NewBlockRef(testBlockID(startBlock+1), startBlock+1)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator, _ := initializedValidator(t)
			response := blockResponse(startBlock, nil)
			cursor, err := bstream.CursorFromOpaque(response.GetBlockScopedData().Cursor)
			if err != nil {
				t.Fatal(err)
			}
			test.mutate(cursor)
			response.GetBlockScopedData().Cursor = cursor.ToOpaque()
			if err := validator.handle(response); err == nil {
				t.Fatal("foreign cursor passed")
			}
		})
	}
}

func TestIrreversibleOnlyCursorStepIsAccepted(t *testing.T) {
	validator, _ := initializedValidator(t)
	response := blockResponse(startBlock, nil)
	cursor, err := bstream.CursorFromOpaque(response.GetBlockScopedData().Cursor)
	if err != nil {
		t.Fatal(err)
	}
	cursor.Step = bstream.StepIrreversible
	response.GetBlockScopedData().Cursor = cursor.ToOpaque()
	if err := validator.handle(response); err != nil {
		t.Fatalf("irreversible-only cursor rejected: %v", err)
	}
}

func TestBlockTimestampsMustStrictlyIncrease(t *testing.T) {
	validator, _ := initializedValidator(t)
	first := blockResponse(startBlock, nil)
	if err := validator.handle(first); err != nil {
		t.Fatal(err)
	}
	second := blockResponse(startBlock+1, nil)
	second.GetBlockScopedData().Clock.Timestamp = first.GetBlockScopedData().Clock.Timestamp
	if err := validator.handle(second); err == nil {
		t.Fatal("non-increasing timestamp passed")
	}
}

func TestWriterErrorsAreRejected(t *testing.T) {
	validator := newStreamValidator(errorWriter{})
	if err := validator.handle(sessionResponse()); err != nil {
		t.Fatal(err)
	}
	if err := validator.handle(blockResponse(startBlock, nil)); err == nil {
		t.Fatal("writer error passed")
	}
}

type errorWriter struct{}

func (errorWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

type fixtureStreamServer struct {
	pbsubstreamsrpcv3.UnimplementedStreamServer
	mode string
}

func (server fixtureStreamServer) Blocks(
	request *pbsubstreamsrpcv3.Request,
	stream grpc.ServerStreamingServer[pbsubstreamsrpc.Response],
) error {
	metadataValues, ok := metadata.FromIncomingContext(stream.Context())
	if !ok || len(metadataValues.Get("x-api-key")) != 1 || metadataValues.Get("x-api-key")[0] != "fixture-secret" ||
		len(metadataValues.Get("authorization")) != 0 {
		return status.Error(codes.Unauthenticated, "auth contract drift")
	}
	if request.Package == nil || !proto.Equal(request, requestFor(request.Package)) {
		return status.Error(codes.InvalidArgument, "request contract drift")
	}
	if err := stream.Send(sessionResponse()); err != nil {
		return err
	}
	if server.mode == "status" {
		return status.Error(codes.DataLoss, "fixture status")
	}
	if server.mode == "hang" {
		<-stream.Context().Done()
		return stream.Context().Err()
	}
	lastExclusive := stopBlock
	if server.mode == "early-eof" {
		lastExclusive--
	}
	for block := startBlock; block < lastExclusive; block++ {
		if err := stream.Send(blockResponse(block, []byte{byte(block)})); err != nil {
			return err
		}
	}
	if server.mode == "extra" {
		if err := stream.Send(blockResponse(stopBlock, nil)); err != nil {
			return err
		}
	}
	if server.mode == "final-progress" {
		if err := stream.Send(&pbsubstreamsrpc.Response{Message: &pbsubstreamsrpc.Response_Progress{
			Progress: &pbsubstreamsrpc.ModulesProgress{
				ProcessedBlocks: blockCount,
				ProcessedBytes:  &pbsubstreamsrpc.ProcessedBytes{},
			},
		}}); err != nil {
			return err
		}
	}
	return nil
}

func fixtureTLS(t *testing.T) (credentials.TransportCredentials, credentials.TransportCredentials) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	template := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: "localhost"},
		DNSNames:     []string{"localhost"},
		NotBefore:    now.Add(-time.Minute),
		NotAfter:     now.Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := tls.X509KeyPair(
		pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}),
		pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}),
	)
	if err != nil {
		t.Fatal(err)
	}
	parsedCertificate, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	pool := x509.NewCertPool()
	pool.AddCert(parsedCertificate)
	serverCredentials := credentials.NewTLS(&tls.Config{
		MinVersion:   tls.VersionTLS12,
		Certificates: []tls.Certificate{certificate},
	})
	clientCredentials := credentials.NewTLS(&tls.Config{
		MinVersion: tls.VersionTLS12,
		RootCAs:    pool,
		ServerName: "localhost",
	})
	return serverCredentials, clientCredentials
}

func validPackage() *pbsubstreams.Package {
	return &pbsubstreams.Package{
		Network: "mainnet",
		Modules: &pbsubstreams.Modules{Modules: []*pbsubstreams.Module{{
			Name: outputModule,
			Kind: &pbsubstreams.Module_KindMap_{KindMap: &pbsubstreams.Module_KindMap{
				OutputType: packageOutputType,
			}},
		}}},
	}
}

func runAgainstFixtureServer(t *testing.T, mode string) (string, error) {
	t.Helper()
	serverCredentials, clientCredentials := fixtureTLS(t)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := grpc.NewServer(grpc.Creds(serverCredentials))
	pbsubstreamsrpcv3.RegisterStreamServer(server, fixtureStreamServer{mode: mode})
	done := make(chan struct{})
	go func() {
		_ = server.Serve(listener)
		close(done)
	}()
	t.Cleanup(func() {
		server.Stop()
		_ = listener.Close()
		<-done
	})

	packageRaw, err := proto.Marshal(validPackage())
	if err != nil {
		t.Fatal(err)
	}
	packagePath := filepath.Join(t.TempDir(), "fixture.spkg")
	if err := os.WriteFile(packagePath, packageRaw, 0o600); err != nil {
		t.Fatal(err)
	}
	_, port, err := net.SplitHostPort(listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	clientIdentity := artifactIdentity{SHA256: strings.Repeat("f", 64), Bytes: 123}
	var output bytes.Buffer
	timeout := 10 * time.Second
	if mode == "hang" {
		timeout = 50 * time.Millisecond
	}
	err = run(runConfig{
		Endpoint:           net.JoinHostPort("localhost", port),
		PackagePath:        packagePath,
		SessionID:          strings.Repeat("a", 64),
		InvocationID:       strings.Repeat("b", 64),
		Role:               "candidate",
		SourceRevision:     strings.Repeat("c", 40),
		StartedAtUnixNanos: time.Now().Add(-time.Second).UnixNano(),
		Stdout:             &output,
		Timeout:            timeout,
		Transport:          clientCredentials,
		Auth:               staticAuth{key: "x-api-key", value: "fixture-secret"},
		AuthKind:           "x-api-key",
		ClientIdentity:     &clientIdentity,
	})
	return output.String(), err
}

func TestRealTLSProtocolV3RunRequiresCleanCompleteEOF(t *testing.T) {
	output, err := runAgainstFixtureServer(t, "complete")
	if err != nil {
		t.Fatalf("complete stream failed: %v", err)
	}
	lines := strings.Split(strings.TrimSuffix(output, "\n"), "\n")
	if len(lines) != int(blockCount)+1 {
		t.Fatalf("complete stream line count %d", len(lines))
	}
	var completion completionRecord
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &completion); err != nil {
		t.Fatal(err)
	}
	if completion.SessionID != strings.Repeat("a", 64) ||
		completion.InvocationID != strings.Repeat("b", 64) ||
		completion.Role != "candidate" || completion.Endpoint == "" || completion.RequestSHA256 == "" ||
		completion.Package.Bytes < 1 || completion.CaptureClient.SHA256 != strings.Repeat("f", 64) {
		t.Fatalf("completion provenance drift: %#v", completion)
	}
}

func TestRealTLSProtocolV3RunAcceptsFinalProgressBeforeCleanEOF(t *testing.T) {
	output, err := runAgainstFixtureServer(t, "final-progress")
	if err != nil {
		t.Fatalf("block -> final progress -> EOF stream failed: %v", err)
	}
	lines := strings.Split(strings.TrimSuffix(output, "\n"), "\n")
	if len(lines) != int(blockCount)+1 {
		t.Fatalf("final-progress stream line count %d", len(lines))
	}
	var completion completionRecord
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &completion); err != nil {
		t.Fatal(err)
	}
	if !completion.Completed || completion.BlockCount != blockCount || completion.LastBlock != stopBlock-1 {
		t.Fatalf("final-progress stream completion drift: %#v", completion)
	}
}

func TestRealTLSProtocolV3RunRejectsEarlyEOFExtraStatusAndHang(t *testing.T) {
	for _, mode := range []string{"early-eof", "extra", "status", "hang"} {
		t.Run(mode, func(t *testing.T) {
			output, err := runAgainstFixtureServer(t, mode)
			if err == nil {
				t.Fatalf("%s stream passed", mode)
			}
			if strings.Contains(output, completionRecordKind) {
				t.Fatalf("%s stream emitted a completion record", mode)
			}
		})
	}
}

func TestEndpointRequiresStrictDNSNameAndNumericPort(t *testing.T) {
	for _, endpoint := range []string{
		"https://localhost:443",
		"user:secret@example.test:443",
		"localhost:https",
		"localhost:0",
		"localhost:65536",
		"[::1]:443",
		"127.0.0.1:443",
		"-bad.example:443",
		"bad-.example:443",
		"bad..example:443",
		"localhost:443/path",
	} {
		t.Run(strconv.Quote(endpoint), func(t *testing.T) {
			if _, err := endpointCredentials(endpoint); err == nil {
				t.Fatalf("malformed endpoint passed: %s", endpoint)
			}
		})
	}
}
