package main

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"hash"
	"io"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/streamingfast/bstream"
	pbsubstreamsrpc "github.com/streamingfast/substreams/pb/sf/substreams/rpc/v2"
	pbsubstreamsrpcv3 "github.com/streamingfast/substreams/pb/sf/substreams/rpc/v3"
	pbsubstreams "github.com/streamingfast/substreams/pb/sf/substreams/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/protobuf/proto"
)

const (
	clientVersion        = "uniswap-v3-mainnet-parity-client-v1"
	upstreamVersion      = "v1.20.3"
	upstreamCommit       = "cc555bd4e325b65ac3f95dfde4655076f88d4a0a"
	upstreamTree         = "38ea588549e5e41698da00ee149278aa2d855c64"
	startBlock           = uint64(12369621)
	stopBlock            = uint64(12370674)
	blockCount           = stopBlock - startBlock
	outputModule         = "graph_out"
	outputType           = "sf.substreams.entity.v1.EntityChanges"
	packageOutputType    = "proto:" + outputType
	outputTypeURL        = "type.googleapis.com/" + outputType
	blockRecordKind      = "uniswap-v3-mainnet-parity-block"
	completionRecordKind = "uniswap-v3-mainnet-parity-stream-completion"
	requestTimeout       = 2 * time.Hour
	maxCursorBytes       = 64 * 1024
	maxResponseBytes     = 64 * 1024 * 1024
	maxPackageBytes      = 256 * 1024 * 1024
)

var (
	blockIDPattern  = regexp.MustCompile(`^[0-9a-f]{64}$`)
	hex40Pattern    = regexp.MustCompile(`^[0-9a-f]{40}$`)
	hex64Pattern    = regexp.MustCompile(`^[0-9a-f]{64}$`)
	dnsLabelPattern = regexp.MustCompile(`^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$`)
)

type artifactIdentity struct {
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
}

type requestContract struct {
	ProtocolVersion                     int               `json:"protocol_version"`
	Network                             string            `json:"network"`
	Module                              string            `json:"module"`
	OutputType                          string            `json:"output_type"`
	StartBlock                          uint64            `json:"start_block"`
	StartCursor                         string            `json:"start_cursor"`
	EndBlockExclusive                   uint64            `json:"end_block_exclusive"`
	ProcessedBlockLimit                 uint64            `json:"processed_block_limit"`
	FinalBlocksOnly                     bool              `json:"final_blocks_only"`
	ProductionMode                      bool              `json:"production_mode"`
	NoopMode                            bool              `json:"noop_mode"`
	PartialBlocks                       bool              `json:"partial_blocks"`
	MaxRetries                          int               `json:"max_retries"`
	Params                              map[string]string `json:"params"`
	DebugInitialStoreSnapshotForModules []string          `json:"debug_initial_store_snapshot_for_modules"`
	DevOutputModules                    []string          `json:"dev_output_modules"`
	Package                             artifactIdentity  `json:"package"`
}

type invocationBinding struct {
	SessionID          string
	InvocationID       string
	Role               string
	SourceRevision     string
	Endpoint           string
	AuthKind           string
	Package            artifactIdentity
	CaptureClient      artifactIdentity
	Request            requestContract
	RequestSHA256      string
	SanitizedArgv      []string
	StartedAtUnixNanos int64
}

type blockRecord struct {
	FormatVersion    int    `json:"format_version"`
	Kind             string `json:"kind"`
	Block            uint64 `json:"block"`
	BlockID          string `json:"block_id"`
	TimestampSeconds int64  `json:"timestamp_seconds"`
	TimestampNanos   int32  `json:"timestamp_nanos"`
	Module           string `json:"module"`
	OutputType       string `json:"output_type"`
	MapOutputBase64  string `json:"map_output_base64"`
	MapOutputBytes   int    `json:"map_output_bytes"`
	MapOutputSHA256  string `json:"map_output_sha256"`
	CursorSHA256     string `json:"cursor_sha256"`
}

type completionRecord struct {
	FormatVersion        int              `json:"format_version"`
	Kind                 string           `json:"kind"`
	ClientVersion        string           `json:"client_version"`
	ProtocolVersion      int              `json:"protocol_version"`
	UpstreamVersion      string           `json:"upstream_version"`
	UpstreamCommit       string           `json:"upstream_commit"`
	UpstreamTree         string           `json:"upstream_tree"`
	SessionID            string           `json:"session_id"`
	InvocationID         string           `json:"invocation_id"`
	Role                 string           `json:"role"`
	SourceRevision       string           `json:"source_revision"`
	Endpoint             string           `json:"endpoint"`
	AuthKind             string           `json:"auth_kind"`
	Package              artifactIdentity `json:"package"`
	CaptureClient        artifactIdentity `json:"capture_client"`
	Request              requestContract  `json:"request"`
	RequestSHA256        string           `json:"request_sha256"`
	SanitizedArgv        []string         `json:"sanitized_argv"`
	StartedAtUnixNanos   int64            `json:"started_at_unix_nanos"`
	CompletedAtUnixNanos int64            `json:"completed_at_unix_nanos"`
	FirstBlock           uint64           `json:"first_block"`
	LastBlock            uint64           `json:"last_block"`
	BlockCount           uint64           `json:"block_count"`
	RecordsSHA256        string           `json:"records_sha256"`
	Completed            bool             `json:"completed"`
}

type streamValidator struct {
	w             io.Writer
	sessionSeen   bool
	expectedBlock uint64
	recordCount   uint64
	lastBlock     uint64
	lastTimestamp time.Time
	recordsDigest hash.Hash
}

func newStreamValidator(w io.Writer) *streamValidator {
	return &streamValidator{w: w, expectedBlock: startBlock, recordsDigest: sha256.New()}
}

func (v *streamValidator) handle(response *pbsubstreamsrpc.Response) error {
	if response == nil || response.Message == nil {
		return errors.New("nil protocol response")
	}
	switch message := response.Message.(type) {
	case *pbsubstreamsrpc.Response_Session:
		return v.handleSession(message.Session)
	case *pbsubstreamsrpc.Response_Progress:
		if !v.sessionSeen || message.Progress == nil {
			return errors.New("invalid progress response")
		}
		return nil
	case *pbsubstreamsrpc.Response_BlockScopedData:
		return v.handleBlock(message.BlockScopedData)
	case *pbsubstreamsrpc.Response_BlockUndoSignal:
		return errors.New("undo response is forbidden")
	case *pbsubstreamsrpc.Response_FatalError:
		return errors.New("remote fatal response")
	case *pbsubstreamsrpc.Response_DebugSnapshotData:
		return errors.New("snapshot response is forbidden")
	case *pbsubstreamsrpc.Response_DebugSnapshotComplete:
		return errors.New("snapshot completion is forbidden")
	default:
		return errors.New("unknown protocol response")
	}
}

func (v *streamValidator) handleSession(session *pbsubstreamsrpc.SessionInit) error {
	if session == nil || v.sessionSeen || v.recordCount != 0 {
		return errors.New("invalid or duplicate session")
	}
	if session.ResolvedStartBlock != startBlock {
		return errors.New("session range contract mismatch")
	}
	v.sessionSeen = true
	return nil
}

func (v *streamValidator) handleBlock(data *pbsubstreamsrpc.BlockScopedData) error {
	if !v.sessionSeen || data == nil || data.Clock == nil || data.Output == nil || data.Output.MapOutput == nil {
		return errors.New("block response has nil required data")
	}
	if data.IsPartial || data.PartialIndex != nil || data.IsLastPartial != nil {
		return errors.New("partial block response is forbidden")
	}
	if len(data.DebugMapOutputs) != 0 || len(data.DebugStoreOutputs) != 0 {
		return errors.New("response must contain exactly one map output")
	}
	if data.Output.Name != outputModule || data.Output.MapOutput.TypeUrl != outputTypeURL {
		return errors.New("map output contract mismatch")
	}
	if data.Clock.Number != v.expectedBlock || data.Clock.Number >= stopBlock {
		return errors.New("block response is missing, duplicate, or out of range")
	}
	if !blockIDPattern.MatchString(data.Clock.Id) || data.FinalBlockHeight != data.Clock.Number {
		return errors.New("block hash or finality contract mismatch")
	}
	if data.Clock.Timestamp == nil || data.Clock.Timestamp.CheckValid() != nil {
		return errors.New("block timestamp is absent or invalid")
	}
	timestamp := data.Clock.Timestamp.AsTime()
	if !v.lastTimestamp.IsZero() && !timestamp.After(v.lastTimestamp) {
		return errors.New("block timestamps are not strictly increasing")
	}
	if data.Cursor == "" || len(data.Cursor) > maxCursorBytes {
		return errors.New("block cursor is absent")
	}
	cursor, err := bstream.CursorFromOpaque(data.Cursor)
	if err != nil || cursor == nil || cursor.Block == nil || cursor.LIB == nil ||
		(cursor.Step != bstream.StepIrreversible && cursor.Step != bstream.StepNewIrreversible) ||
		cursor.Block.Num() != data.Clock.Number || cursor.Block.ID() != data.Clock.Id ||
		cursor.LIB.Num() != data.Clock.Number || cursor.LIB.ID() != data.Clock.Id {
		return errors.New("block cursor does not bind the response")
	}

	value := data.Output.MapOutput.Value
	cursorHash := sha256.Sum256([]byte(data.Cursor))
	mapOutputHash := sha256.Sum256(value)
	record := blockRecord{
		FormatVersion:    1,
		Kind:             blockRecordKind,
		Block:            data.Clock.Number,
		BlockID:          data.Clock.Id,
		TimestampSeconds: data.Clock.Timestamp.Seconds,
		TimestampNanos:   data.Clock.Timestamp.Nanos,
		Module:           data.Output.Name,
		OutputType:       outputType,
		MapOutputBase64:  base64.StdEncoding.EncodeToString(value),
		MapOutputBytes:   len(value),
		MapOutputSHA256:  hex.EncodeToString(mapOutputHash[:]),
		CursorSHA256:     hex.EncodeToString(cursorHash[:]),
	}
	encoded, err := json.Marshal(record)
	if err != nil {
		return errors.New("could not encode block record")
	}
	encoded = append(encoded, '\n')
	if written, err := v.w.Write(encoded); err != nil || written != len(encoded) {
		return errors.New("could not write block record")
	}
	if _, err := v.recordsDigest.Write(encoded); err != nil {
		return errors.New("could not hash block record")
	}
	v.recordCount++
	v.lastBlock = data.Clock.Number
	v.lastTimestamp = timestamp
	v.expectedBlock++
	return nil
}

func (v *streamValidator) finish(binding invocationBinding) error {
	if !v.sessionSeen || v.recordCount != blockCount || v.expectedBlock != stopBlock || v.lastBlock != stopBlock-1 {
		return errors.New("stream ended before the complete fixed range")
	}
	completedAt := time.Now().UnixNano()
	if binding.StartedAtUnixNanos <= 0 || completedAt < binding.StartedAtUnixNanos {
		return errors.New("capture clock bounds are invalid")
	}
	completion := completionRecord{
		FormatVersion:        1,
		Kind:                 completionRecordKind,
		ClientVersion:        clientVersion,
		ProtocolVersion:      3,
		UpstreamVersion:      upstreamVersion,
		UpstreamCommit:       upstreamCommit,
		UpstreamTree:         upstreamTree,
		SessionID:            binding.SessionID,
		InvocationID:         binding.InvocationID,
		Role:                 binding.Role,
		SourceRevision:       binding.SourceRevision,
		Endpoint:             binding.Endpoint,
		AuthKind:             binding.AuthKind,
		Package:              binding.Package,
		CaptureClient:        binding.CaptureClient,
		Request:              binding.Request,
		RequestSHA256:        binding.RequestSHA256,
		SanitizedArgv:        binding.SanitizedArgv,
		StartedAtUnixNanos:   binding.StartedAtUnixNanos,
		CompletedAtUnixNanos: completedAt,
		FirstBlock:           startBlock,
		LastBlock:            stopBlock - 1,
		BlockCount:           blockCount,
		RecordsSHA256:        hex.EncodeToString(v.recordsDigest.Sum(nil)),
		Completed:            true,
	}
	encoded, err := json.Marshal(completion)
	if err != nil {
		return errors.New("could not encode completion record")
	}
	encoded = append(encoded, '\n')
	if written, err := v.w.Write(encoded); err != nil || written != len(encoded) {
		return errors.New("could not write completion record")
	}
	return nil
}

func validatePackage(pkg *pbsubstreams.Package) error {
	if pkg == nil || pkg.Modules == nil || pkg.Network != "mainnet" {
		return errors.New("package is not an Ethereum mainnet package")
	}
	matches := 0
	for _, module := range pkg.Modules.Modules {
		if module == nil || module.Name != outputModule {
			continue
		}
		matches++
		if module.GetKindMap() == nil || module.GetKindMap().OutputType != packageOutputType {
			return errors.New("package graph_out output type mismatch")
		}
	}
	if matches != 1 {
		return errors.New("package must contain exactly one graph_out module")
	}
	return nil
}

func requestFor(pkg *pbsubstreams.Package) *pbsubstreamsrpcv3.Request {
	return &pbsubstreamsrpcv3.Request{
		StartBlockNum:        int64(startBlock),
		StopBlockNum:         stopBlock,
		FinalBlocksOnly:      true,
		ProductionMode:       false,
		OutputModule:         outputModule,
		Package:              pkg,
		Network:              "mainnet",
		NoopMode:             false,
		LimitProcessedBlocks: blockCount,
		DevOutputModules:     []string{outputModule},
		PartialBlocks:        false,
	}
}

func endpointCredentials(endpoint string) (credentials.TransportCredentials, error) {
	host, port, err := net.SplitHostPort(endpoint)
	if err != nil || !validDNSName(host) || port == "" {
		return nil, errors.New("endpoint must be a credential-free host:port")
	}
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return nil, errors.New("endpoint port is invalid")
	}
	return credentials.NewTLS(&tls.Config{MinVersion: tls.VersionTLS12, ServerName: host}), nil
}

func validDNSName(host string) bool {
	if host == "" || len(host) > 253 || net.ParseIP(host) != nil {
		return false
	}
	labels := strings.Split(host, ".")
	for _, label := range labels {
		if !dnsLabelPattern.MatchString(label) {
			return false
		}
	}
	return true
}

type staticAuth struct {
	key   string
	value string
}

func (a staticAuth) GetRequestMetadata(context.Context, ...string) (map[string]string, error) {
	return map[string]string{a.key: a.value}, nil
}

func (staticAuth) RequireTransportSecurity() bool {
	return true
}

func authorization() (credentials.PerRPCCredentials, string, error) {
	apiKey := os.Getenv("SUBSTREAMS_API_KEY")
	apiToken := os.Getenv("SUBSTREAMS_API_TOKEN")
	if (apiKey == "") == (apiToken == "") {
		return nil, "", errors.New("set exactly one Substreams credential")
	}
	if apiKey != "" {
		return staticAuth{key: "x-api-key", value: apiKey}, "x-api-key", nil
	}
	return staticAuth{key: "authorization", value: "Bearer " + apiToken}, "bearer-token", nil
}

func fileIdentity(path string, maximumBytes int64, field string) ([]byte, artifactIdentity, error) {
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
		return nil, artifactIdentity{}, fmt.Errorf("%s is not a regular file", field)
	}
	if info.Size() < 1 || info.Size() > maximumBytes {
		return nil, artifactIdentity{}, fmt.Errorf("%s size is outside the capture contract", field)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, artifactIdentity{}, fmt.Errorf("could not read %s", field)
	}
	digest := sha256.Sum256(raw)
	return raw, artifactIdentity{SHA256: hex.EncodeToString(digest[:]), Bytes: int64(len(raw))}, nil
}

func selfIdentity() (artifactIdentity, error) {
	executable, err := os.Executable()
	if err != nil {
		return artifactIdentity{}, errors.New("could not resolve capture-client binary")
	}
	executable, err = filepath.EvalSymlinks(executable)
	if err != nil {
		return artifactIdentity{}, errors.New("could not resolve capture-client binary")
	}
	_, identity, err := fileIdentity(executable, 512*1024*1024, "capture-client binary")
	return identity, err
}

func contractFor(packageIdentity artifactIdentity) requestContract {
	return requestContract{
		ProtocolVersion:                     3,
		Network:                             "mainnet",
		Module:                              outputModule,
		OutputType:                          outputType,
		StartBlock:                          startBlock,
		StartCursor:                         "",
		EndBlockExclusive:                   stopBlock,
		ProcessedBlockLimit:                 blockCount,
		FinalBlocksOnly:                     true,
		ProductionMode:                      false,
		NoopMode:                            false,
		PartialBlocks:                       false,
		MaxRetries:                          0,
		Params:                              map[string]string{},
		DebugInitialStoreSnapshotForModules: []string{},
		DevOutputModules:                    []string{outputModule},
		Package:                             packageIdentity,
	}
}

func requestDigest(contract requestContract) (string, error) {
	raw, err := json.Marshal(contract)
	if err != nil {
		return "", errors.New("could not encode request contract")
	}
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:]), nil
}

func validateInvocationMetadata(sessionID, invocationID, role, sourceRevision string, startedAtUnixNanos int64) error {
	if !hex64Pattern.MatchString(sessionID) || !hex64Pattern.MatchString(invocationID) ||
		!hex40Pattern.MatchString(sourceRevision) {
		return errors.New("capture provenance identity is malformed")
	}
	if role != "baseline" && role != "candidate" {
		return errors.New("capture role is invalid")
	}
	if startedAtUnixNanos <= 0 || startedAtUnixNanos > time.Now().Add(time.Minute).UnixNano() {
		return errors.New("capture start clock is invalid")
	}
	return nil
}

type runConfig struct {
	Endpoint           string
	PackagePath        string
	SessionID          string
	InvocationID       string
	Role               string
	SourceRevision     string
	StartedAtUnixNanos int64
	Stdout             io.Writer
	Timeout            time.Duration
	Transport          credentials.TransportCredentials
	Auth               credentials.PerRPCCredentials
	AuthKind           string
	ClientIdentity     *artifactIdentity
}

func run(config runConfig) error {
	if config.Stdout == nil {
		return errors.New("capture stdout writer is missing")
	}
	if err := validateInvocationMetadata(
		config.SessionID,
		config.InvocationID,
		config.Role,
		config.SourceRevision,
		config.StartedAtUnixNanos,
	); err != nil {
		return err
	}
	raw, packageIdentity, err := fileIdentity(config.PackagePath, maxPackageBytes, "package")
	if err != nil {
		return err
	}
	var pkg pbsubstreams.Package
	if err := proto.Unmarshal(raw, &pkg); err != nil {
		return errors.New("could not decode package")
	}
	if err := validatePackage(&pkg); err != nil {
		return err
	}
	transportCredentials := config.Transport
	if transportCredentials == nil {
		transportCredentials, err = endpointCredentials(config.Endpoint)
		if err != nil {
			return err
		}
	}
	auth := config.Auth
	authKind := config.AuthKind
	if auth == nil {
		auth, authKind, err = authorization()
		if err != nil {
			return err
		}
	}
	if authKind != "x-api-key" && authKind != "bearer-token" {
		return errors.New("capture auth kind is invalid")
	}
	clientIdentity := artifactIdentity{}
	if config.ClientIdentity == nil {
		clientIdentity, err = selfIdentity()
		if err != nil {
			return err
		}
	} else {
		clientIdentity = *config.ClientIdentity
		if !hex64Pattern.MatchString(clientIdentity.SHA256) || clientIdentity.Bytes < 1 {
			return errors.New("capture-client identity is malformed")
		}
	}
	requestContract := contractFor(packageIdentity)
	requestSHA256, err := requestDigest(requestContract)
	if err != nil {
		return err
	}
	conn, err := grpc.NewClient(
		config.Endpoint,
		grpc.WithTransportCredentials(transportCredentials),
		grpc.WithPerRPCCredentials(auth),
		grpc.WithDisableRetry(),
		grpc.WithUserAgent(clientVersion),
		grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(maxResponseBytes)),
	)
	if err != nil {
		return errors.New("could not create protocol-v3 client")
	}
	defer conn.Close()

	timeout := config.Timeout
	if timeout == 0 {
		timeout = requestTimeout
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	stream, err := pbsubstreamsrpcv3.NewStreamClient(conn).Blocks(ctx, requestFor(&pkg))
	if err != nil {
		return errors.New("protocol-v3 request was refused")
	}
	validator := newStreamValidator(config.Stdout)
	binding := invocationBinding{
		SessionID:      config.SessionID,
		InvocationID:   config.InvocationID,
		Role:           config.Role,
		SourceRevision: config.SourceRevision,
		Endpoint:       config.Endpoint,
		AuthKind:       authKind,
		Package:        packageIdentity,
		CaptureClient:  clientIdentity,
		Request:        requestContract,
		RequestSHA256:  requestSHA256,
		SanitizedArgv: []string{
			"uniswap-v3-mainnet-parity-client",
			"--endpoint", config.Endpoint,
			"--package", "<package:" + config.Role + ">",
			"--session-id", config.SessionID,
			"--invocation-id", config.InvocationID,
			"--role", config.Role,
			"--source-revision", config.SourceRevision,
			"--started-at-unix-nanos", strconv.FormatInt(config.StartedAtUnixNanos, 10),
		},
		StartedAtUnixNanos: config.StartedAtUnixNanos,
	}
	for {
		response, receiveErr := stream.Recv()
		if errors.Is(receiveErr, io.EOF) {
			return validator.finish(binding)
		}
		if receiveErr != nil {
			return errors.New("protocol-v3 stream failed")
		}
		if err := validator.handle(response); err != nil {
			return err
		}
	}
}

func main() {
	endpoint := flag.String("endpoint", "", "credential-free Substreams host:port")
	packagePath := flag.String("package", "", "local package path")
	sessionID := flag.String("session-id", "", "capture session identity")
	invocationID := flag.String("invocation-id", "", "capture invocation identity")
	role := flag.String("role", "", "capture role")
	sourceRevision := flag.String("source-revision", "", "repository source revision")
	startedAtUnixNanos := flag.Int64("started-at-unix-nanos", 0, "wrapper capture start clock")
	showVersion := flag.Bool("version", false, "print the capture client identity")
	flag.Parse()
	if *showVersion {
		fmt.Printf("%s (protocol v3; upstream %s %s)\n", clientVersion, upstreamVersion, upstreamCommit)
		return
	}
	if flag.NArg() != 0 || *endpoint == "" || *packagePath == "" || *sessionID == "" ||
		*invocationID == "" || *role == "" || *sourceRevision == "" || *startedAtUnixNanos == 0 {
		fmt.Fprintln(os.Stderr, "parity capture client failed: complete capture arguments are required")
		os.Exit(1)
	}
	if err := run(runConfig{
		Endpoint:           *endpoint,
		PackagePath:        *packagePath,
		SessionID:          *sessionID,
		InvocationID:       *invocationID,
		Role:               *role,
		SourceRevision:     *sourceRevision,
		StartedAtUnixNanos: *startedAtUnixNanos,
		Stdout:             os.Stdout,
	}); err != nil {
		fmt.Fprintf(os.Stderr, "parity capture client failed: %s\n", err)
		os.Exit(1)
	}
}
