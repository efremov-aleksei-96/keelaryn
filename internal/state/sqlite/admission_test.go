package sqlitestate

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestHardenedNewDerivesCompleteAuthorityAndCommitsAtomically(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	at:=time.Date(2026,9,25,21,0,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-new","obj-new",nil,at))
	got,err:=store.AcceptNewObservationInScan(ctx,identityRequest("req-new",scan.ID,"obj-new","file-id/obj-new","auth-new",at,"same")); if err!=nil { t.Fatal(err) }
	if got.Replayed || got.Observation.ArtifactID=="" || got.Revision==nil || !got.Revision.Created || got.Decision.State!=corpus.OccurrenceIdentityResolvedNew || got.Decision.AuthoritySetID!="auth-new" || got.Binding.ArtifactID!=got.Observation.ArtifactID { t.Fatalf("acceptance=%#v",got) }
	stored,err:=store.AcceptedAdmission(ctx,"req-new"); if err!=nil { t.Fatal(err) }
	if stored.ArtifactID!=got.Observation.ArtifactID || stored.AuthoritySetID!="auth-new" { t.Fatalf("stored=%#v",stored) }
}

func TestHardenedNewExactReplayReturnsOriginalWithoutMutation(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	at:=time.Date(2026,9,25,21,1,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-new-replay","obj-replay",nil,at))
	request:=identityRequest("req-new-replay",scan.ID,"obj-replay","file-id/obj-replay","auth-new-replay",at,"same")
	first,err:=store.AcceptNewObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	beforeArtifacts:=internalTableCount(t,store.Path(),"artifacts"); beforeObs:=internalTableCount(t,store.Path(),"observations")
	second,err:=store.AcceptNewObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	if !second.Replayed || second.Observation.ID!=first.Observation.ID || second.Observation.ArtifactID!=first.Observation.ArtifactID || !second.Decision.DecidedAt.Equal(first.Decision.DecidedAt) { t.Fatalf("replay=%#v",second) }
	if internalTableCount(t,store.Path(),"artifacts")!=beforeArtifacts || internalTableCount(t,store.Path(),"observations")!=beforeObs { t.Fatal("replay mutated durable state") }
}

func TestHardenedNewRequestIDParameterMismatchFailsClosed(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	at:=time.Date(2026,9,25,21,2,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-new-mismatch","obj-mismatch",nil,at))
	request:=identityRequest("req-new-mismatch",scan.ID,"obj-mismatch","file-id/obj-mismatch","auth-new-mismatch",at,"same")
	if _,err=store.AcceptNewObservationInScan(ctx,request); err!=nil { t.Fatal(err) }
	before:=internalTableCount(t,store.Path(),"artifacts")
	request.ContentEvidence=ptrInternalEvidence(internalEvidence("diff",4))
	_,err=store.AcceptNewObservationInScan(ctx,request)
	if !errors.Is(err,ErrIdentityMutationParameterMismatch) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"artifacts")!=before { t.Fatal("mismatch minted Artifact") }
}

func TestHardenedNewUnknownUniverseCannotAuthorizeMutation(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	at:=time.Date(2026,9,25,21,3,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	authority:=newAuthority("auth-unknown","obj-unknown",nil,at); authority.UniverseCoverage=corpus.CandidateUniverseUnknown
	seedAuthoritySet(t,store,authority)
	before:=internalTableCount(t,store.Path(),"artifacts")
	_,err=store.AcceptNewObservationInScan(ctx,identityRequest("req-unknown",scan.ID,"obj-unknown","file-id/obj-unknown","auth-unknown",at,"same"))
	if !errors.Is(err,ErrInvalidArtifactAdmission) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"artifacts")!=before { t.Fatal("UNKNOWN authority minted Artifact") }
}

func TestHardenedNewCompleteAuthorityWithSameCandidateCannotAuthorizeNew(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	artifact,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,21,4,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-has-same","obj-has-same",[]corpus.IdentityAuthorityCandidate{{ArtifactID:artifact.ID,Direction:corpus.DirectionSupportsSame,SourceRef:"test:same"}},at))
	before:=internalTableCount(t,store.Path(),"artifacts")
	_,err=store.AcceptNewObservationInScan(ctx,identityRequest("req-has-same",scan.ID,"obj-has-same","file-id/obj-has-same","auth-has-same",at,"same"))
	if !errors.Is(err,ErrInvalidArtifactAdmission) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"artifacts")!=before { t.Fatal("SAME authority minted Artifact") }
}

func TestHardenedNewIdenticalBytesDistinctAuthorityCreatesDistinctArtifact(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	original,err:=store.AdoptArtifact(ctx); if err!=nil { t.Fatal(err) }
	if _,err=store.ObserveRevision(ctx,original.ID,internalEvidence("same",4)); err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,21,5,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-copy","obj-copy",[]corpus.IdentityAuthorityCandidate{{ArtifactID:original.ID,Direction:corpus.DirectionSupportsDistinct,SourceRef:"drive:file-id-distinct"}},at))
	got,err:=store.AcceptNewObservationInScan(ctx,identityRequest("req-copy",scan.ID,"obj-copy","file-id/obj-copy","auth-copy",at,"same")); if err!=nil { t.Fatal(err) }
	if got.Observation.ArtifactID==original.ID { t.Fatal("identical-byte copy reused Artifact") }
	if got.Revision==nil || got.Revision.Current.Evidence.Digest!="same" { t.Fatalf("revision=%#v",got.Revision) }
}

func TestHardenedNewDifferentRequestCannotReadmitBoundProviderObject(t *testing.T) {
	ctx:=context.Background(); store:=openInternalStore(t)
	base:=time.Date(2026,9,25,21,6,0,0,time.UTC)
	firstScan,err:=store.StartScan(ctx,"drive","drive-root",base); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-bound-1","obj-bound",nil,base))
	if _,err=store.AcceptNewObservationInScan(ctx,identityRequest("req-bound-1",firstScan.ID,"obj-bound","file-id/obj-bound","auth-bound-1",base,"same")); err!=nil { t.Fatal(err) }
	if err=store.CompleteScan(ctx,firstScan.ID,base.Add(time.Minute)); err!=nil { t.Fatal(err) }
	secondAt:=base.Add(2*time.Minute); secondScan,err:=store.StartScan(ctx,"drive","drive-root",secondAt); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-bound-2","obj-bound",nil,secondAt))
	before:=internalTableCount(t,store.Path(),"artifacts")
	_,err=store.AcceptNewObservationInScan(ctx,identityRequest("req-bound-2",secondScan.ID,"obj-bound","file-id/obj-bound","auth-bound-2",secondAt,"same"))
	if !errors.Is(err,ErrProviderObjectAlreadyBound) { t.Fatalf("error=%v",err) }
	if internalTableCount(t,store.Path(),"artifacts")!=before { t.Fatal("bound object minted another Artifact") }
}

func TestHardenedNewReplaySurvivesReopen(t *testing.T) {
	ctx:=context.Background(); path:=filepath.Join(t.TempDir(),"state.db")
	store,err:=Open(ctx,path); if err!=nil { t.Fatal(err) }
	at:=time.Date(2026,9,25,21,7,0,0,time.UTC)
	scan,err:=store.StartScan(ctx,"drive","drive-root",at); if err!=nil { t.Fatal(err) }
	seedAuthoritySet(t,store,newAuthority("auth-new-reopen","obj-new-reopen",nil,at))
	request:=identityRequest("req-new-reopen",scan.ID,"obj-new-reopen","file-id/obj-new-reopen","auth-new-reopen",at,"same")
	first,err:=store.AcceptNewObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	if err=store.Close(); err!=nil { t.Fatal(err) }
	store,err=Open(ctx,path); if err!=nil { t.Fatal(err) }; defer store.Close()
	second,err:=store.AcceptNewObservationInScan(ctx,request); if err!=nil { t.Fatal(err) }
	if !second.Replayed || second.Observation.ID!=first.Observation.ID || second.Observation.ArtifactID!=first.Observation.ArtifactID { t.Fatalf("replay=%#v",second) }
}
