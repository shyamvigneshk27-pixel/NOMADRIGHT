# Source - https://stackoverflow.com/a/1057534
# Posted by Anurag Uniyal, modified by community. See post 'Timeline' for change history
# Retrieved 2026-01-30, License - CC BY-SA 4.0

from os.path import dirname, basename, isfile, join
import glob
modules = glob.glob(join(dirname(__file__), "*.py"))
__all__ = [ basename(f)[:-3] for f in modules if isfile(f) and not f.endswith('__init__.py')]

try:
    from pocketinfer.applications.nomad_right.app import NomadRightApplication
    __all__.append("NomadRightApplication")
except ImportError:
    pass

