package corpus_test

import (
	"testing"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/corpus"
)

func TestIdentityMutationFingerprintCanonicalizesLocatorOrder(t *testing.T) {
	at:=time.Date(2026,9,25,22,0,0,0,time.UTC)
	request:=corpus.IdentityMutationRequest{
		ID:"req-1",ScanID:"scan-1",AuthoritySetID:"auth-1",
		Observation:corpus.ObservationRecordInput{
			ProviderObject:corpus.ProviderObject{ProviderID:"drive",ID:"obj-1",IdentityState:corpus.ObjectIdentityObserved},
			Locators:[]corpus.Locator{{ProviderID:"drive",Root:"root",Path:"b"},{ProviderID:"drive",Root:"root",Path:"a"}},
			AssignmentState:corpus.AssignmentUnresolved,ObservedAt:at,Kind:corpus.EntryRegularFile,Size:4,Mode:0o600,ModifiedAt:at,
		},
		ContentEvidence:&corpus.ContentEvidence{Algorithm:corpus.ContentAlgorithmSHA256,Digest:"same",Size:4},DecidedAt:at,
	}
	first,err:=corpus.FingerprintIdentityMutation(corpus.IdentityMutationSame,request); if err!=nil { t.Fatal(err) }
	request.Observation.Locators[0],request.Observation.Locators[1]=request.Observation.Locators[1],request.Observation.Locators[0]
	request.DecidedAt=at.Add(time.Hour)
	second,err:=corpus.FingerprintIdentityMutation(corpus.IdentityMutationSame,request); if err!=nil { t.Fatal(err) }
	if first!=second { t.Fatalf("fingerprint changed: %#v %#v",first,second) }
}

func TestIdentityMutationFingerprintChangesWithSemanticInput(t *testing.T) {
	at:=time.Date(2026,9,25,22,1,0,0,time.UTC)
	request:=corpus.IdentityMutationRequest{
		ID:"req-1",ScanID:"scan-1",AuthoritySetID:"auth-1",
		Observation:corpus.ObservationRecordInput{
			ProviderObject:corpus.ProviderObject{ProviderID:"drive",ID:"obj-1",IdentityState:corpus.ObjectIdentityObserved},
			Locators:[]corpus.Locator{{ProviderID:"drive",Root:"root",Path:"a"}},
			AssignmentState:corpus.AssignmentUnresolved,ObservedAt:at,Kind:corpus.EntryRegularFile,Size:4,Mode:0o600,ModifiedAt:at,
		},
		ContentEvidence:&corpus.ContentEvidence{Algorithm:corpus.ContentAlgorithmSHA256,Digest:"same",Size:4},DecidedAt:at,
	}
	first,err:=corpus.FingerprintIdentityMutation(corpus.IdentityMutationNew,request); if err!=nil { t.Fatal(err) }
	request.AuthoritySetID="auth-2"
	second,err:=corpus.FingerprintIdentityMutation(corpus.IdentityMutationNew,request); if err!=nil { t.Fatal(err) }
	if first.SHA256==second.SHA256 { t.Fatal("semantic change did not change fingerprint") }
}
