#!/usr/bin/env python3
"""Local-only fake OAuth device flow. No Google HTTP, no real credentials."""
import json
from pathlib import Path
import os
import stat
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import drive_device_auth as auth


def setup(base):
    conf=base/"etc";state=base/"state"
    conf.mkdir(mode=0o700);state.mkdir(mode=0o700)
    auth.CONFIG=conf;auth.STATE=state
    for name,data in (("client-id","12345-abc.apps.googleusercontent.com"),
                      ("client-secret","synthetic-test-secret-not-real")):
        p=conf/name;p.write_text(data);p.chmod(0o600)


class Mock:
    def __init__(self):
        self.token_steps=["authorization_pending","approved"]
        self.calls=[]
    def __call__(self,url,data):
        self.calls.append((url,{k:v for k,v in data.items() if k!="client_secret"}))
        if url==auth.DEVICE_URL:
            assert data["scope"]==auth.SCOPE
            return 200, {"device_code":"synthetic-device-code-value",
                         "user_code":"ABCD-EFGH","verification_url":"https://www.google.com/device",
                         "expires_in":1800,"interval":5}
        assert url==auth.TOKEN_URL
        if data["grant_type"]=="refresh_token":
            assert data["refresh_token"]=="synthetic-refresh-token"
            return 200,{"access_token":"synthetic-fresh-access",
                        "token_type":"Bearer","expires_in":3600,"scope":auth.SCOPE}
        assert data["client_secret"]=="synthetic-test-secret-not-real"
        status=self.token_steps.pop(0)
        if status=="authorization_pending": return 428,{"error":"authorization_pending"}
        return 200,{"access_token":"synthetic-access-token",
                    "refresh_token":"synthetic-refresh-token",
                    "token_type":"Bearer","scope":auth.SCOPE,"expires_in":3600}


def main():
    with tempfile.TemporaryDirectory(prefix="keelaryn-oauth-test-") as tmp:
        root=Path(tmp)
        setup(root)
        api=Mock()
        fresh=auth.start(post=api,now=lambda:1000)
        assert fresh["status"]=="ready" and fresh["user_code"]=="ABCD-EFGH"
        assert auth.start(post=api,now=lambda:1002)["status"]=="existing"
        assert auth.poll(post=api,now=lambda:1005)["status"]=="pending"
        assert auth.poll(post=api,now=lambda:1006)["status"]=="wait"
        result=auth.poll(post=api,now=lambda:1011)
        assert result=={"status":"authorized","scope":auth.SCOPE,"refresh_stored":True}
        saved=root/"state"/"refresh-token.json"
        st=saved.stat()
        assert stat.S_IMODE(st.st_mode)==0o600 and st.st_uid==os.geteuid()
        raw=json.loads(saved.read_text())
        assert raw["refresh_token"]=="synthetic-refresh-token"
        assert auth.poll(post=api,now=lambda:1018)["status"]=="already_authorized"
        assert auth.fresh_access_token(post=api)=="synthetic-fresh-access"
        assert len([x for x in api.calls if x[0]==auth.DEVICE_URL])==1
        print("GOOGLE_DEVICE_OAUTH_FAKE_CONSENT_REFRESH_PASS")
    with tempfile.TemporaryDirectory(prefix="keelaryn-oauth-wrong-scope-") as tmp:
        setup(Path(tmp))
        api=Mock()
        auth.start(post=api,now=lambda:2000)
        def wrong_scope(url,data):
            if url==auth.TOKEN_URL:
                return 200,{"access_token":"synthetic-access-token",
                            "refresh_token":"synthetic-refresh-token",
                            "token_type":"Bearer","scope":"https://www.googleapis.com/auth/drive"}
            return api(url,data)
        try: auth.poll(post=wrong_scope,now=lambda:2010)
        except auth.AuthError: pass
        else: raise AssertionError("Drive full-scope response incorrectly accepted")
        assert not (auth.STATE/"refresh-token.json").exists()
        print("GOOGLE_DEVICE_OAUTH_EXCESS_SCOPE_DENIED_PASS")


if __name__=="__main__": main()
