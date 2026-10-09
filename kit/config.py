"""config.py - where things live. Importable from Blender's Python and from plain python3.

Every path the kit touches outside the repo goes through here, so nothing is hard-coded to one machine.
Override with environment variables (defaults in brackets):

  ARCH_KIT_MODELS   downloaded / prepped 3D models, not committed        [<repo>/models]
  ARCH_KIT_MUSIC    music files, not committed                            [<repo>/music]
  ARCH_KIT_OUT      renders, frames, anchors, videos, not committed       [<repo>/out]
  ARCH_KIT_FONTS    folder with NotoSansSC-{Bold,Medium,Black}.ttf (OFL)   [~/Library/Fonts]
  ARCH_KIT_SERIF    serif font file for carved inscriptions               [macOS Times New Roman]
  ARCH_KIT_DIN      font for dimension numbers (optional graphics layer)  [macOS DIN Alternate Bold; Noto if missing]
  BLENDER           Blender executable (used by blender_locked.sh)        [/Applications/Blender.app/.../Blender]
  ARCH_BLENDER_LOCK lock dir that keeps one Blender running at a time     [<ARCH_KIT_OUT>/.blender.lock]

Paths inside episode / prep JSON files are resolved with resolve(path, base):
  absolute or ~ paths          as given ($VARS are expanded)
  "models/...", "music/...", "out/..."   -> under ARCH_KIT_MODELS / ARCH_KIT_MUSIC / ARCH_KIT_OUT
  anything else                relative to `base` (the JSON file's folder)
"""
import os

KIT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(KIT_DIR)


def _env_dir(name, default):
    v = os.environ.get(name)
    return os.path.abspath(os.path.expanduser(v)) if v else default


MODELS_DIR = _env_dir("ARCH_KIT_MODELS", os.path.join(REPO_DIR, "models"))
MUSIC_DIR = _env_dir("ARCH_KIT_MUSIC", os.path.join(REPO_DIR, "music"))
OUT_DIR = _env_dir("ARCH_KIT_OUT", os.path.join(REPO_DIR, "out"))
FONT_DIR = _env_dir("ARCH_KIT_FONTS", os.path.expanduser("~/Library/Fonts"))
SERIF_FONT = os.path.expanduser(os.environ.get("ARCH_KIT_SERIF",
                                               "/System/Library/Fonts/Supplemental/Times New Roman.ttf"))
DIN_FONT = os.path.expanduser(os.environ.get("ARCH_KIT_DIN",
                                             "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"))
BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")

_ROOTS = {"models": lambda: MODELS_DIR, "music": lambda: MUSIC_DIR, "out": lambda: OUT_DIR}


def resolve(path, base=None):
    """Resolve a path written in an episode / prep JSON (see module doc)."""
    p = os.path.expanduser(os.path.expandvars(str(path)))
    if os.path.isabs(p):
        return os.path.normpath(p)
    parts = p.replace("\\", "/").split("/")
    if parts[0] in _ROOTS:
        return os.path.normpath(os.path.join(_ROOTS[parts[0]](), *parts[1:]))
    return os.path.normpath(os.path.join(base or REPO_DIR, p))


def find_config(path):
    """Episode JSON given on the command line: as given (cwd), else relative to the repo root, else to kit/."""
    p = os.path.expanduser(path)
    if os.path.isabs(p):
        return p
    for d in (os.getcwd(), REPO_DIR, KIT_DIR):
        c = os.path.join(d, p)
        if os.path.exists(c):
            return os.path.abspath(c)
    return os.path.abspath(p)


if __name__ == "__main__":
    for k in ("KIT_DIR", "REPO_DIR", "MODELS_DIR", "MUSIC_DIR", "OUT_DIR", "FONT_DIR", "SERIF_FONT", "DIN_FONT", "BLENDER"):
        print("%-11s %s" % (k, globals()[k]))
