import json, tempfile, unittest
from pathlib import Path
try:
    from app.main_window.main import EditorMainWindow
except Exception:
    EditorMainWindow = None
@unittest.skipIf(EditorMainWindow is None, "PySide6 or editor imports unavailable")
class ProjectStatePersistenceTests(unittest.TestCase):
    def test_json_safe_preserves_nested_clip_properties(self):
        data=[{"name":"V1","clips":[{"opacity":0.65,"keyframes":[{"time":1.0,"value":0.5}]}]}]
        safe=EditorMainWindow._json_safe(data)
        self.assertEqual(safe[0]["clips"][0]["opacity"],0.65)
        self.assertEqual(safe[0]["clips"][0]["keyframes"][0]["value"],0.5)
    def test_unsupported_object_is_omitted_not_null(self):
        class Transient: pass
        self.assertEqual(EditorMainWindow._json_safe({"keep":1,"transient":Transient()}), {"keep":1})
    def test_legacy_project_json_can_restore_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"project.json").write_text(json.dumps({"tracks":[{"clips":[{"path":"clip.mp4"}]}]}),encoding="utf-8")
            instance=object.__new__(EditorMainWindow); instance.root_dir=root; instance.project_state_path=root/"project_state.json"
            payload,source=EditorMainWindow._read_saved_state(instance)
            self.assertEqual(payload["tracks"][0]["clips"][0]["path"],"clip.mp4")
            self.assertEqual(source.name,"project.json")
if __name__ == "__main__": unittest.main()
