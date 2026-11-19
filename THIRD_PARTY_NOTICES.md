# Third-party notices

The source code in this repository uses only the Python standard library. The release `PicoCompanion.exe` is built with
PyInstaller and therefore bundles the following components:

| Component | License |
|---|---|
| CPython runtime (and standard library) | [Python Software Foundation License](https://docs.python.org/3/license.html) |
| Tcl/Tk (used by `tkinter`) | [Tcl/Tk license (BSD-style)](https://www.tcl-lang.org/software/tcltk/license.html) |
| PyInstaller bootloader | GPL-2.0-or-later with a special exception that allows bundling it in applications under any license. See the [PyInstaller license](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt). |

The bundled components remain under their own licenses; the MIT license in this repository covers only the
code of this project.
