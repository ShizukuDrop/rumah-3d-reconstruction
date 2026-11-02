"""No-network checks for remote.py: subprocess.run is replaced and the script runs from a temp copy so upload.sftp stays there."""
import contextlib,io,os,runpy,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

SOURCE=Path(__file__).with_name('remote.py');STAGE='/var/lib/vz/rumah-deploy/'

class RemoteCli(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.script=root/'a'/'b'/'remote.py';self.script.parent.mkdir(parents=True);shutil.copy(SOURCE,self.script)
        self.local=root/'payload.tar';self.local.write_bytes(b'x');self.calls=[]
        env=mock.patch.dict(os.environ,{'RUMAH_SSH_HOST':'test-host','RUMAH_SSH_CONFIG':str(root/'missing.json')});env.start();self.addCleanup(env.stop)
    def cli(self,*argv):
        def fake(cmd,**kw):self.calls.append((cmd,kw));return subprocess.CompletedProcess(cmd,0,b'',b'')
        with mock.patch.object(subprocess,'run',fake),mock.patch.object(sys,'argv',[str(self.script),*argv]),contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO())),contextlib.redirect_stderr(io.TextIOWrapper(io.BytesIO())):
            with self.assertRaises(SystemExit) as done:runpy.run_path(str(self.script),run_name='__main__')
        return done.exception.code
    def test_put_uses_access_settings(self):
        self.assertEqual(self.cli('--put',str(self.local),STAGE+'run/native-site.tar','--limit','60'),0)
        (cmd,kw),=self.calls;self.assertEqual((cmd[0],cmd[-1],kw['timeout']),('sftp','test-host',60));self.assertIn('BatchMode=yes',cmd)
        self.assertEqual((self.script.parent/'upload.sftp').read_text(encoding='utf-8'),f'put -a "{self.local.resolve().as_posix()}" "{STAGE}run/native-site.tar"\n')
    def test_put_rejects_paths(self):
        for remote in (STAGE+'../../..',STAGE+'a/../b','/var/lib/vz/rumah-deploy/','/var/lib/vz/rumah-deploy',STAGE+'a//b',STAGE+'a/./b',STAGE+'a/','/tmp/x',STAGE+'a"b',STAGE+"a'b",STAGE+'a\\b',STAGE+'a\nb',STAGE+'a\rb'):
            with self.subTest(remote=remote),self.assertRaises(ValueError):self.cli('--put',str(self.local),remote)
        # A backslash is a separator on Windows, so only POSIX can name a file with one.
        for name in ('q"uote',"q'uote",'new\nline')+(('back\\slash',) if os.name!='nt' else ()):
            with self.subTest(local=name),self.assertRaises(ValueError):self.cli('--put',str(self.local.parent/name),STAGE+'ok')
        self.assertEqual(self.calls,[])
    def test_script_timeout_follows_limit(self):
        body=self.local.with_name('s.sh');body.write_bytes(b'echo hi\r\n')
        for limit,remote in (('45',40),('195',190),('3',1)):
            self.calls.clear();self.assertEqual(self.cli('--script',str(body),'--limit',limit),0)
            (cmd,kw),=self.calls;self.assertEqual((cmd[-1],kw['timeout'],kw['input']),(f'timeout -s TERM {remote} bash -s',int(limit),b'echo hi\n'))
    def test_no_action_or_two_actions_is_usage_error(self):
        self.assertEqual(self.cli(),2);self.assertEqual(self.cli('--limit','5'),2);self.assertEqual(self.cli('--command','true','--script','x'),2);self.assertEqual(self.calls,[])
    def test_help_opens_no_connection(self):
        with mock.patch.dict(os.environ,{'RUMAH_SSH_HOST':''}):self.assertEqual(self.cli('--help'),0)
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
