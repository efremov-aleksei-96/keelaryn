package sqlitestate

import (
	"context"
	"testing"
	"time"

	"zombiezen.com/go/sqlite/sqlitex"
)

func TestIdentityAuthorityAndMutationReceiptsAreSealed(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,22,30,0,0,time.UTC)
	set:=sameAuthority("auth-sealed",artifact.ID,"obj-sealed",at)
	seedAuthoritySet(t,store,set)

	conn,err:=store.pool.Get(ctx); if err!=nil { t.Fatal(err) }
	defer store.pool.Put(conn)

	for name,query,args:=range []struct{name,query string; args []any}{
		{"update-set","UPDATE identity_authority_sets SET policy_id='changed' WHERE authority_set_id=?1",[]any{string(set.ID)}},
		{"delete-set","DELETE FROM identity_authority_sets WHERE authority_set_id=?1",[]any{string(set.ID)}},
		{"insert-candidate-after-seal","INSERT INTO identity_authority_candidates (authority_set_id,artifact_id,direction,source_ref) VALUES (?1,?2,'SUPPORTS_DISTINCT','late')",[]any{string(set.ID),string(artifact.ID)}},
		{"update-candidate","UPDATE identity_authority_candidates SET source_ref='changed' WHERE authority_set_id=?1",[]any{string(set.ID)}},
		{"delete-candidate","DELETE FROM identity_authority_candidates WHERE authority_set_id=?1",[]any{string(set.ID)}},
	} {
		t.Run(name,func(t *testing.T){
			if err:=sqlitex.Execute(conn,query,&sqlitex.ExecOptions{Args:args}); err==nil {
				t.Fatalf("%s unexpectedly succeeded",name)
			}
		})
	}

	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	if _,err=store.AcceptSameObservationInScan(ctx,identityRequest("req-sealed",scan.ID,"obj-sealed","file-id/obj-sealed",set.ID,at,"same")); err!=nil { t.Fatal(err) }

	conn2,err:=store.pool.Get(ctx)
	if err==nil {
		store.pool.Put(conn2)
		t.Fatal("pool unexpectedly yielded a second connection while first is held")
	}
}

func TestIdentityMutationReceiptRejectsUpdateDelete(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	at:=time.Date(2026,9,25,22,31,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-receipt","obj-receipt",nil,at))
	if _,err=store.AcceptNewObservationInScan(ctx,identityRequest("req-receipt",scan.ID,"obj-receipt","file-id/obj-receipt","auth-receipt",at,"same")); err!=nil { t.Fatal(err) }

	conn,err:=store.pool.Get(ctx); if err!=nil { t.Fatal(err) }
	defer store.pool.Put(conn)
	if err:=sqlitex.Execute(conn,"UPDATE identity_mutation_requests SET fingerprint_sha256='changed' WHERE request_id='req-receipt'",nil); err==nil {
		t.Fatal("identity mutation receipt UPDATE unexpectedly succeeded")
	}
	if err:=sqlitex.Execute(conn,"DELETE FROM identity_mutation_requests WHERE request_id='req-receipt'",nil); err==nil {
		t.Fatal("identity mutation receipt DELETE unexpectedly succeeded")
	}
}
