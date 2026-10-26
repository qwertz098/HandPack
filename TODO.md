# TODO

- **Encoding pausieren/fortsetzen unter Windows**: Linux/Docker-Teil ist
  bereits umgesetzt (`EncodeWorker.pause()`/`resume()` in jobs.py via
  `SIGSTOP`/`SIGCONT`, Pause-Button in gui.py). Unter Windows ist der Button
  aktuell bewusst deaktiviert (`can_pause()` = False), da es kein
  SIGSTOP-Äquivalent für Prozesse gibt – müsste über die WinAPI
  (`SuspendThread`/`ResumeThread` je Thread, z. B. via `pywin32` oder
  `ctypes`) nachgerüstet werden.
