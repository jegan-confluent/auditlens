"""Compatibility shim for the deprecated bootstrap installer."""

from scripts.deprecated import bootstrap_auditlens as _impl
from scripts.deprecated.bootstrap_auditlens import *  # noqa: F401,F403


def validate_runtime(inputs):
    _impl.wait_for_http_json = wait_for_http_json
    _impl.wait_for_http_status = wait_for_http_status
    return _impl.validate_runtime(inputs)


if __name__ == "__main__":
    import sys
    sys.exit(_impl.main())
