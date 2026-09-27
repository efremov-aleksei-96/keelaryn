package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory"
	"github.com/efremov-aleksei-96/keelaryn/internal/remotehistory/gdrive"
	"zombiezen.com/go/sqlite"
	"zombiezen.com/go/sqlite/sqlitemigration"
	"zombiezen.com/go/sqlite/sqlitex"
)

func TestGoogleDriveTopologyApplicationAuthorityRejectsDirectSQL(t *testing.T) {
	ctx := context.Background()
	store := openStoreInternal(t)
	scope := remotehistory.Scope{
		ProviderID: gdrive.ProviderID,
		IdentityDomain: "drive:user-1",
		StreamID: "drive:user-1:changes",
		Root: "root",
	}
	fp := remotehistory.ScopePolicyFingerprint("scope-policy:v1:gdrive")
	base := time.Date(2026, 9, 27, 18, 30, 0, 0, time.UTC)
	bundle := gdrive.BootstrapBundle{
		History: remotehistory.BootstrapResult{
			StreamID: scope.StreamID,
			Status: remotehistory.BootstrapComplete,
			Cursor: "cursor-1",
			Coverage: corpus.ProviderHistoryContinuous,
			Objects: []remotehistory.RemoteObjectState{{
				ObjectID: "child",
				Locators: []corpus.Locator{{ProviderID:gdrive.ProviderID,Root:"root",Path:"child"}},
			}},
		},
		Topology: []gdrive.TopologyState{{
			ObjectID:"child", Presence:gdrive.TopologyPresent, ParentKnowledge:gdrive.ParentUnknown, DriveID:"drive-a",
		}},
	}
	generation, err := store.StartGoogleDriveRemoteHistoryGeneration(ctx, scope, fp, bundle, base)
	if err != nil {
		t.Fatal(err)
	}

	conn, err := store.pool.Get(ctx)
	if err != nil { t.Fatal(err) }
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_evidence (generation_id,sequence,ordinal,evidence_kind,object_id,presence,parent_state,parent_id,drive_id) VALUES (?1,1,-1,'BOOTSTRAP','forged','PRESENT','UNKNOWN',NULL,'drive-a')",
		&sqlitex.ExecOptions{Args:[]any{string(generation.ID)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct topology evidence insert unexpectedly succeeded")
	}
	if err := sqlitex.Execute(conn,
		"INSERT INTO gdrive_managed_root_bindings (generation_id,managed_root_object_id,bound_sequence,created_at) VALUES (?1,'root',1,?2)",
		&sqlitex.ExecOptions{Args:[]any{string(generation.ID),base.Add(time.Second).Format(time.RFC3339Nano)}}); err == nil {
		store.pool.Put(conn)
		t.Fatal("direct managed-root binding insert unexpectedly succeeded")
	}
	store.pool.Put(conn)

	if _, err := store.BindGoogleDriveManagedRoot(ctx,generation.ID,"root",base.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}

func TestQualifiedV41DatabaseMigratesToGoogleDriveTopologyAuthorityV42(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(),"v41.db")
	legacy := &Store{path:path}
	v41 := sqlitemigration.Schema{AppID:applicationID,Migrations:append([]string(nil),schema.Migrations[:41]...)}
	pool := sqlitemigration.NewPool(path,v41,sqlitemigration.Options{
		Flags:sqlite.OpenReadWrite|sqlite.OpenCreate,PoolSize:1,PrepareConn:legacy.prepareConn,
	})
	legacy.pool=pool
	conn,err:=pool.Get(ctx); if err!=nil {t.Fatal(err)}
	pool.Put(conn); if err:=pool.Close(); err!=nil {t.Fatal(err)}

	store,err:=Open(ctx,path); if err!=nil {t.Fatal(err)}
	defer store.Close()
	conn,err=store.pool.Get(ctx); if err!=nil {t.Fatal(err)}
	defer store.pool.Put(conn)
	for _,name:=range []string{
		"gdrive_topology_evidence_insert_application_guard_v42",
		"gdrive_topology_nodes_insert_application_guard_v42",
		"gdrive_topology_nodes_update_application_guard_v42",
		"gdrive_topology_watermarks_insert_application_guard_v42",
		"gdrive_topology_watermarks_delete_application_guard_v42",
		"gdrive_managed_root_bindings_insert_application_guard_v42",
	}{
		var found bool
		if err:=sqlitex.Execute(conn,"SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?1",
			&sqlitex.ExecOptions{Args:[]any{name},ResultFunc:func(*sqlite.Stmt)error{found=true;return nil}});err!=nil{t.Fatal(err)}
		if !found {t.Fatalf("v41→v42 migration missing %s",name)}
	}
}

func TestHistoricalGoogleTopologySemanticMismatchFailsClosed(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(),"v41-topology.db")
	legacy := &Store{path:path}
	v41 := sqlitemigration.Schema{AppID:applicationID,Migrations:append([]string(nil),schema.Migrations[:41]...)}
	pool := sqlitemigration.NewPool(path,v41,sqlitemigration.Options{
		Flags:sqlite.OpenReadWrite|sqlite.OpenCreate,PoolSize:1,PrepareConn:legacy.prepareConn,
	})
	legacy.pool=pool
	conn,err:=pool.Get(ctx); if err!=nil {t.Fatal(err)}
	// A provider-valid RemoteHistory shell with structurally valid but semantically
	// invalid topology (PRESENT + UNKNOWN is valid; use self-parent KNOWN to violate
	// gdrive.ValidateTopologyEvidence while satisfying the old SQL shape would not,
	// so create an evidence/source mismatch that the historical verifier must reject).
	// The legacy row set is deliberately partial: any topology durable state must
	// verify as a complete projection at Open.
	base:=time.Date(2026,9,27,18,35,0,0,time.UTC).Format(time.RFC3339Nano)
	if err:=sqlitex.Execute(conn,
		"INSERT INTO remote_history_generations (generation_id,provider_id,identity_domain,stream_id,root,scope_policy_fingerprint,status,created_at,closed_at,closure_reason,current_sequence,committed_cursor) VALUES ('hgen_gdrive_legacy','google-drive','drive:user-1','drive:user-1:changes','root','scope-policy:v1:gdrive','ACTIVE',?1,NULL,NULL,1,'cursor-1')",
		&sqlitex.ExecOptions{Args:[]any{base}});err!=nil{t.Fatal(err)}
	// Use a correct empty-bootstrap fingerprint so v41 RemoteHistory historical verification passes.
	pub:=remotehistory.HistoryPublication{
		GenerationID:"hgen_gdrive_legacy",Sequence:1,Kind:remotehistory.HistoryPublicationBootstrap,
		CommittedCursor:"cursor-1",CommittedAt:time.Date(2026,9,27,18,35,0,0,time.UTC),
		FingerprintVersion:remoteHistoryPublicationFingerprintVersion,
	}
	fp,err:=bootstrapPublicationFingerprint(pub,[]remotehistory.RemoteObjectState{});if err!=nil{t.Fatal(err)}
	if err:=sqlitex.Execute(conn,
		"INSERT INTO remote_history_publications (generation_id,sequence,kind,previous_cursor,committed_cursor,committed_at,fingerprint_version,fingerprint_sha256) VALUES ('hgen_gdrive_legacy',1,'BOOTSTRAP','','cursor-1',?1,?2,?3)",
		&sqlitex.ExecOptions{Args:[]any{base,pub.FingerprintVersion,fp}});err!=nil{t.Fatal(err)}
	if err:=sqlitex.Execute(conn,
		"INSERT INTO gdrive_topology_watermarks (generation_id,publication_sequence) VALUES ('hgen_gdrive_legacy',1)",nil);err!=nil{t.Fatal(err)}
	pool.Put(conn); if err:=pool.Close();err!=nil{t.Fatal(err)}

	reopened,err:=Open(ctx,path)
	if reopened!=nil {_=reopened.Close()}
	if !errors.Is(err,ErrGoogleDriveHistoricalAuthorityInvalid){
		t.Fatalf("Open error=%v want ErrGoogleDriveHistoricalAuthorityInvalid",err)
	}
}
