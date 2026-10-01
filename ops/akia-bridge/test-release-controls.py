"""Pure env-override tests; never invokes Docker or connects to a service."""
import json, pathlib, subprocess, sys, tempfile, unittest
SOURCE=pathlib.Path(__file__).with_name('release-akia-service.sh').read_text().split("<<'PY'\n",1)[1].split('\nPY',1)[0]
FLAGS=['NORTH_RUNTIME_COMMENTS_ENABLED','NORTH_RUNTIME_TASK_EDIT_ENABLED','NORTH_RUNTIME_CLIENT_EDIT_ENABLED','NORTH_RUNTIME_SETTINGS_ENABLED']
class Controls(unittest.TestCase):
 def render(self,unit,old,desired,activate=True):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)
   (p/'desired-config.json').write_text(json.dumps({'services':{unit:{'environment':desired}}}))
   (p/'old-inspect.json').write_text(json.dumps([{'Config':{'Image':'old@sha256:'+'a'*64,'Env':[k+'='+v for k,v in old.items()]}}]))
   r=subprocess.run([sys.executable,'-c',SOURCE,d,unit,'new@sha256:'+'b'*64,str(activate).lower()],capture_output=True)
   if r.returncode:return None
   return tuple(json.loads((p/name).read_text())['services'][unit] for name in ['candidate.json','rollback.json'])
 def test_operations_activation_only_flags_preserves_dollars(self):
  old={**dict.fromkeys(FLAGS,'false'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true','SECRET':'a$b${c}'}
  candidate,rollback=self.render('operations-api',old,{'UNRELATED':'must-not-enter'})
  self.assertEqual(set(candidate['environment']),set(old))
  for k in FLAGS:self.assertEqual(candidate['environment'][k],'true');self.assertEqual(rollback['environment'][k],'false')
  self.assertEqual(candidate['environment']['SECRET'],'a$$b$${c}')
  self.assertEqual(rollback['image'],'old@sha256:'+'a'*64)
 def test_gateway_only_delegation(self):
  old={'SECRET':'opaque','AKIA_NORTH_DELEGATION_ENABLED':'false'}
  c,r=self.render('akia-gateway',old,{'UNRELATED':'no'})
  self.assertEqual(c['environment'],{**old,'AKIA_NORTH_DELEGATION_ENABLED':'true'})
  self.assertEqual(r['environment'],old)
 def test_invalid_stage_rejected(self):
  self.assertIsNone(self.render('operations-api',{},{}))
 def test_new_keys_removed_by_rollback(self):
  desired={**dict.fromkeys(FLAGS,'false'),'OPERATIONS_NORTH_DELEGATION_ENABLED':'true','NORTH_SHARED_TRILHAS_APPROVED':'true','NEW':'value'}
  c,r=self.render('operations-api',{'OLD':'value'},desired,False)
  self.assertIsNone(r['environment']['NEW']);self.assertEqual(r['environment']['OLD'],'value')
if __name__=='__main__':unittest.main()
