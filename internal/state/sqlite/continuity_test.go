package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestHardenedSameDerivesAuthorityAndReusesUnchangedRevision(t *testing.T) {
	ctx := context.Background(); store := openInternalStore(t)
	artifact, err := store.AdoptArtifact(ctx); if err != nil { t.Fatal(err) }
	first, err := store.ObserveRevision(ctx, artifact.ID, internalEvidence("same", 4)); if err != nil { t.Fatal(err) }
	at := time.Date(2026,9,25,20,0,0,0,time.UTC)
	scan, err := store.StartScan(ctx,"drive","drive-root",at); if err != nil { t.Fatal(err) }
	seedAuthoritySet(t,store,sameAuthority("auth-same",artifact.ID,"obj-1",at))
	got, err := store.AcceptSameObservationInScan(ctx, identityRequest("req-same",scan.ID,"obj-1","file-id/obj-1","auth-same",at,"same"))
	if err != nil { t.Fatal(err) }
	if got.Replayed || got.Observation.ArtifactID != artifact.ID || got.Observation.RevisionID != first.Current.Revision.ID || got.Revision == nil || got.Revision.Created { t.Fatalf("acceptance=%#v",got) }
	if got.Decision.RequestID != "req-same" || got.Decision.AuthoritySetID != "auth-same" { t.Fatalf("decision=%#v",got.Decision) }
}

func TestHardenedSameChangedContentCreatesNextRevision(t *testing.T) {
	ctx := context.Background(); store := openInternalStore(t)
	artifact, err := store.AdoptArtifact(ctx); if err != nil { t.Fatal(err) }
	if _,err:=store.ObserveRevision(ctx,artifact.ID,internalEvidence("old!",4)); err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,20,1,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,sameAuthority("auth-change",artifact.ID,"obj-2",at))
	got,err:=store.AcceptSameObservationInScan(ctx,identityRequest("req-change",scan.ID,"obj-2","file-id/obj-2","auth-change",at,"new!")); if err!=nil { t.Fatal(err) }
	if got.Revision==nil || !got.Revision.Created || got.Revision.Current.Sequence!=2 { t.Fatalf("revision=%#v",got.Revision) }
}

func TestHardenedSameExactReplayReturnsOriginalWithoutMutation(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	if _,err=store.ObserveRevision(ctx,artifact.ID,internalEvidence("same",4)); err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,20,2,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,sameAuthority("auth-replay",artifact.ID,"obj-3",at))
	request:=identityRequest("req-replay",scan.ID,"obj-3","file-id/obj-3","auth-replay",at,"same")
	first,err:=store.AcceptSameObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	beforeObs:=internalTableCount(t,store.Path(),"observations"); beforeDecisions:=internalTableCount(t,store.Path(),"accepted_continuity_decisions")
	second,err:=store.AcceptSameObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	if !second.Replayed || second.Observation.ID!=first.Observation.ID || second.Decision.ID!=first.Decision.ID || !second.Decision.DecidedAt.Equal(first.Decision.DecidedAt) { t.Fatalf("replay first=%#v second=%#v",first,second) }
	if internalTableCount(t,store.Path(),"observations")!=beforeObs || internalTableCount(t,store.Path(),"accepted_continuity_decisions")!=beforeDecisions { t.Fatal("replay mutated durable state") }
}

func TestHardenedSameRequestIDParameterMismatchFailsClosed(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	if _,err=store.ObserveRevision(ctx,artifact.ID,internalEvidence("same",4)); err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,20,3,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,sameAuthority("auth-mismatch",artifact.ID,"obj-4",at))
	request:=identityRequest("req-mismatch",scan.ID,"obj-4","file-id/obj-4","auth-mismatch",at,"same")
	if _,err=store.AcceptSameObservationInScan(ctx,request); err!=nil { t.Fatal(err) }
	before:=internalTableCount(t,store.Path(),"observations")
	request.Observation.Locators[0].Path="file-id/changed"
	_,err=store.AcceptSameObservationInScan(ctx,request)
	if !errors.Is(err,ErrIdentityMutationParameterMismatch) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"observations")!=before { t.Fatal("mismatch mutated observations") }
}

func TestHardenedSameCallerCannotChooseResolvedState(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,20,4,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	authority:=sameAuthority("auth-distinct",artifact.ID,"obj-5",at); authority.Candidates[0].Direction=corpus.DirectionSupportsDistinct
	seedAuthoritySet(t,store,authority)
	before:=internalTableCount(t,store.Path(),"observations")
	_,err=store.AcceptSameObservationInScan(ctx,identityRequest("req-distinct",scan.ID,"obj-5","file-id/obj-5","auth-distinct",at,"same"))
	if !errors.Is(err,ErrInvalidContinuityAcceptance) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"observations")!=before { t.Fatal("non-SAME authority mutated observations") }
}

func TestHardenedSameReplaySurvivesReopen(t *testing.T) {
	ctx:=context.Background(); path:=filepath.Join(t.TempDir(),"state.db")
	store,err:=Open(ctx,path); if err!=nil { t.Fatal(err) }
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	if _,err=store.ObserveRevision(ctx,artifact.ID,internalEvidence("same",4)); err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,20,5,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,sameAuthority("auth-reopen",artifact.ID,"obj-6",at))
	request:=identityRequest("req-reopen-same",scan.ID,"obj-6","file-id/obj-6","auth-reopen",at,"same")
	first,err:=store.AcceptSameObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	if err=store.Close(); err!=nil { t.Fatal(err) }
	store,err=Open(ctx,path); if err!=nil { t.Fatal(err) }; defer store.Close()
	second,err:=store.AcceptSameObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	if !second.Replayed || second.Observation.ID!=first.Observation.ID || second.Decision.ID!=first.Decision.ID { t.Fatalf("replay=%#v",second) }
}
