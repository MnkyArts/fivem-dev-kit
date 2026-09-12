"""fxkit.scaffold: the fxnew resource generators.

`generator.py` builds the standalone/ESX/QB/qbox/ox skeleton from this
package's own templates; `core_plugin.py` copies core's own
`templates/plugin` for `--framework core` (DESIGN.md section 9.4).
"""
from .generator import ScaffoldOptions, ResourceExistsError, generate, sanitize_name  # noqa: F401
from .core_plugin import (  # noqa: F401
    CorePluginOptions, PluginExistsError, camel_name, generate as generate_core_plugin,
    has_page, next_steps, rewrite_text, validate_name,
)
