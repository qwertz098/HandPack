"""Minimale Internationalisierung: Deutsch / Englisch."""
from __future__ import annotations

from version import APP_NAME, VERSION

_LANG = "en"
_TITLE = f"{APP_NAME} {VERSION}"

_DE: dict[str, str] = {
    # Fenster
    "window_title": _TITLE,
    # Toolbar
    "lbl_target": "Zielauflösung:",
    "lbl_crf": "CRF:",
    "lbl_encoder": "Encoder:",
    "lbl_video_mode": "Video:",
    "video_mode_copy": "Kopieren",
    "lbl_preset": "Preset:",
    "lbl_tune": "Tune:",
    "lbl_outdir": "Ausgabeordner:",
    "lbl_name_tag": "Kürzel:",
    "ph_name_tag": "z. B. MeinTag",
    "tt_name_tag": ("Freies Kürzel, wird ganz ans Ende jedes Ausgabe-"
                    "Dateinamens gehängt (z. B. Encoder-/Gruppenkürzel)"),
    "tt_preset": ("Geschwindigkeit ↔ Qualität (libx265-Presets; "
                  "HW-Encoder werden sinngemäß abgebildet)"),
    "tt_tune": "Inhalts-Tuning – voll wirksam nur bei libx265 (Software)",
    "chk_autocrop": "Crop-Analyse",
    "tt_autocrop": ("Schwarze Balken automatisch erkennen (cropdetect); "
                    "aus = Dateien werden ohne Crop übernommen"),
    "lbl_crop_min": "Min. Crop:",
    "tt_crop_min": ("Crop-Ränder unter diesem Wert (Pixel je Seite) ignorieren, "
                    "damit z. B. FullHD/4K pixelgenau bleibt. 0 = aus"),
    "chk_first_crop": "Nur erste Datei auf Crop prüfen",
    "ph_outdir": "(Quellordner)",
    # Drop-Area
    "drop_hint": "Dateien/Ordner hier ablegen oder klicken",
    "drop_scanning": "Durchsuche Ordner…",
    # Tabellen-Header
    "col_file": "Datei",
    "col_res": "Auflösung",
    "col_crop_on": "Crop",
    "col_crop": "Crop-Wert",
    "col_target": "Ziel",
    "col_hdr": "HDR",
    "col_audio": "Audio",
    "col_crf": "CRF",
    "col_tune": "Tune",
    "col_mono": "S/W",
    "tt_mono": ("Schwarz/Weiß-Encoding (HEVC-Monochrome-Profil, spart "
               "Chroma-Bits) – nur bei libx265 wirksam, kombinierbar mit "
               "jedem Tune. Bei aktivierter Crop-Analyse automatisch "
               "vorausgewählt, wenn die Quelle als farblos erkannt wird "
               "(jederzeit hier übersteuerbar)."),
    "col_encoder": "Encoder",
    "col_preset": "Preset",
    "col_out": "Ausgabe",
    "col_status": "Status",
    # Fußleiste
    "chk_log": "Log",
    "tt_log": "Tool-Ausgaben (ffmpeg, dovi_tool, mkvmerge…) anzeigen",
    "btn_clear_log": "Log leeren",
    "btn_tools_missing": "Fehlende Tools herunterladen",
    "btn_tools_update": "Tool-Updates suchen",
    "btn_start": "Start",
    "btn_pause": "Pause",
    "btn_resume": "Fortsetzen",
    "tt_pause_unsupported": ("Pause ist unter Windows nicht verfügbar "
                             "(kein SIGSTOP-Äquivalent für Prozesse)"),
    "btn_stop": "Stop",
    # Tool-Status
    "tools_ok": "Alle Tools gefunden.",
    "tools_missing": "FEHLT: {names}",
    "tools_no_dovi": "dovi_tool fehlt → DV-Dateien werden als HDR10 encodet.",
    "tools_no_mkv": "mkvmerge fehlt → DV-Mux per ffmpeg (ohne Attachments).{hint}",
    "tools_mkv_hint": " (manuell: mkvtoolnix.download)",
    "tools_current": "Alle Tools aktuell.",
    "tools_searching": "Suche Tool-Updates…",
    # Dialoge
    "dlg_updates_title": "Tool-Updates verfügbar",
    "dlg_updates_text": "Updates verfügbar:\n{lines}\n\nJetzt herunterladen?",
    "dlg_dl_fail_title": "Download fehlgeschlagen",
    "dlg_dl_fail_text": "{msg}\n\nBitte Tool manuell installieren oder erneut versuchen.",
    "dlg_close_title": "Beenden",
    "dlg_close_text": "Ein Encode läuft noch.",
    "dlg_close_info": "Prozess beenden oder im Hintergrund weiterlaufen lassen?",
    "btn_close_stop": "Beenden",
    "btn_close_bg": "Weiterlaufen",
    "btn_close_cancel": "Abbrechen",
    "help_title": "Hilfe / README",
    "help_load_error": "README.md konnte nicht geladen werden: {err}",
    "btn_sysinfo": "System-Info",
    "sysinfo_title": "Systemanalyse",
    "sysinfo_os": "Betriebssystem",
    "sysinfo_encoders": "Erkannte Encoder",
    "sysinfo_x265": "x265-Version",
    "sysinfo_tools": "Externe Tools",
    "sysinfo_col_tool": "Tool",
    "sysinfo_col_version": "Version",
    "sysinfo_col_path": "Pfad",
    "sysinfo_col_encoder": "Encoder",
    "sysinfo_col_fps": "Benchmark",
    "sysinfo_pending": "–",
    "sysinfo_running": "läuft…",
    "sysinfo_run_bench": "Benchmark starten",
    "sysinfo_no_ffmpeg": "ffmpeg nicht gefunden",
    "sysinfo_error": "Fehler",
    # Qualitäts-Vergleich
    "qc_title": "Qualitäts-Vergleich – {name}",
    "qc_encoder": "Encoder",
    "qc_metrics": "Metriken",
    "qc_metric_tip_vmaf": "VMAF (Video Multimethod Assessment Fusion, 0–100,"
                         " höher = besser). Von Netflix entwickelte, an"
                         " menschlichen Bewertungen trainierte Metrik – bildet"
                         " die wahrgenommene Qualität am zuverlässigsten ab,"
                         " besonders bei Kompressionsartefakten. Empfohlener"
                         " Standard für diesen Vergleich.",
    "qc_metric_tip_ssim": "SSIM (Structural Similarity, 0–1, höher = besser)."
                         " Vergleicht lokale Struktur/Kontrast/Luminanz statt"
                         " reiner Pixelwerte. Etablierter Standard, korreliert"
                         " aber schwächer mit menschlicher Wahrnehmung als VMAF,"
                         " besonders bei Blocking-/Ringing-Artefakten.",
    "qc_metric_tip_psnr": "PSNR (Peak Signal-to-Noise Ratio, dB, höher ="
                         " besser). Einfacher, rein pixelweiser"
                         " Differenzvergleich – schnell zu berechnen, aber am"
                         " schlechtesten mit tatsächlich wahrgenommener"
                         " Qualität korreliert. Nur als grober Zusatzwert"
                         " gedacht, nicht als Hauptentscheidungsgrundlage.",
    "qc_vmaf_missing": "libvmaf fehlt in diesem ffmpeg. Für VMAF unter Windows: "
                       "Tools neu herunterladen (Full-Build, braucht 7-Zip).",
    "qc_no_metric": "Mindestens eine Metrik auswählen.",
    "qc_pareto_hint": "★ = nicht von einer anderen Variante dominiert (weder kleiner "
                      "noch besser verfügbar) – sinnvoller als eine Score-pro-MB-Kennzahl, "
                      "da die Qualitätskurve nicht linear zur Dateigröße verläuft.",
    "qc_video_only": "Größenschätzung nur Video (ohne Audio/Untertitel).",
    "qc_dblclick_hint": "Doppelklick auf eine Zeile spielt das Sample ab "
                        "(Original bei der Referenzzeile). Mehrere Zeilen "
                        "auswählen + „Frames vergleichen“ zeigt Einzelbilder nebeneinander.",
    "qc_samples_label": "Samples:",
    "qc_sample_secs_label": "Dauer je Sample:",
    "qc_variants": "Testvarianten",
    "qc_resolutions": "Auflösungen:",
    "qc_crfs": "CRF-Werte (kommagetrennt):",
    "qc_tunes": "Tune:",
    "qc_test_monochrome": "Auch als Schwarz/Weiß testen",
    "qc_test_monochrome_tt": ("Verdoppelt die Varianten-Matrix: jede "
                              "Kombination wird zusätzlich mit aktiviertem "
                              "S/W-Encoding (HEVC-Monochrome-Profil) "
                              "getestet – nur bei libx265 wirksam"),
    "qc_variant_mono": "S/W",
    "qc_count": "{n} Varianten × {samples} Samples à {secs} s",
    "qc_col_variant": "Variante",
    "qc_col_size": "Größe (geschätzt)",
    "qc_col_pct": "% Original",
    "qc_preview_title": "Vorschau – {name}",
    "qc_preview_missing": "Sample-Datei nicht mehr vorhanden.",
    "qc_play": "▶ Abspielen",
    "qc_pause": "⏸ Pause",
    "qc_compare_btn": "Frames vergleichen",
    "qc_compare_title": "Frame-Vergleich",
    "qc_compare_time": "Sekunde im Sample:",
    "qc_compare_refresh": "Aktualisieren",
    "qc_compare_loading": "Lädt…",
    "qc_compare_clip_select": "Testclip für diese Zelle wählen (auch aus vorherigen Einstellungen)",
    "qc_compare_sample": "Sample:",
    "qc_compare_sample_select": "Zwischen den getesteten Sample-Zeitpunkten (z. B. 20/50/80 % der Laufzeit) umschalten",
    "qc_compare_sample_n": "Sample {n}",
    "qc_compare_open_window": "In Fenster öffnen",
    "qc_run_n": "Lauf {n}",
    "qc_original": "Original (Referenz)",
    "qc_start": "Test starten",
    "qc_apply": "Übernehmen",
    "qc_error": "Fehler",
    # Dateidialog
    "fdlg_files_title": "Videodateien wählen",
    "fdlg_files_filter": "Videos (*.mkv *.mp4 *.m4v *.mov *.avi *.ts *.m2ts *.webm);;Alle (*)",
    "fdlg_folder_title": "…oder Ordner wählen",
    "fdlg_outdir_title": "Ausgabeordner",
    # Kontextmenü
    "ctx_reanalyze": "Crop für diese Datei neu analysieren",
    "ctx_preview": "Crop-Vorschau…",
    "ctx_force": "Überschreiben erzwingen",
    "ctx_requeue": "Erneut einreihen",
    "ctx_up": "Nach oben",
    "ctx_down": "Nach unten",
    "ctx_remove": "Aus Liste entfernen",
    "ctx_quality": "Qualitäts-Vergleich…",
    "ctx_media_info": "Medien-Info…",
    "ctx_apply_settings": "Einstellungen auf andere Zeilen übertragen…",
    "apply_settings_title": "Einstellungen übertragen – {name}",
    "apply_settings_what": "Was übernehmen:",
    "apply_settings_audio": "Audio-Auswahl/-Modus (Spur-Overrides)",
    "apply_settings_audio_tt": ("Wird per Spur-Index gematcht (1. Audiospur "
                                "→ 1. Audiospur usw.); bei abweichender "
                                "Spurzahl wird die Zeile für Audio "
                                "übersprungen"),
    "apply_settings_crop": "Crop aktiv/inaktiv",
    "apply_settings_target": "Zielauflösung",
    "apply_settings_tune": "Tune",
    "apply_settings_crf": "CRF",
    "apply_settings_video_mode": "Video-Modus (Encode/Copy)",
    "apply_settings_rows": "Auf diese Zeilen übertragen:",
    "apply_settings_audio_skipped": ("{n} Zeile(n) hatten eine abweichende "
                                     "Audiospur-Anzahl – Audio dort NICHT "
                                     "übernommen, andere Einstellungen schon."),
    # Medien-Info-Dialog
    "mi_title": "Medien-Info – {name}",
    "mi_title_compare": "Medien-Info (Original vs. Ergebnis) – {name}",
    "mi_original": "Original",
    "mi_result": "Ergebnis",
    "mi_container": "Container",
    "mi_total_size": "Gesamtgröße",
    "mi_col_stream": "Stream",
    "mi_col_size": "Größe",
    "mi_col_pct": "Anteil",
    "mi_video_label": "Video: {codec} {w}×{h}",
    "mi_audio_label": "Audio #{n}: {codec}{lang} {ch}ch",
    "mi_subtitle_label": "Untertitel: {codec}",
    "mi_other_stream_label": "Sonstiges: {codec}",
    "mi_other": "Sonstiges (Container-Overhead)",
    "mi_cat_video": "Video",
    "mi_cat_audio": "Audio ({n} Spur(en))",
    "mi_cat_subtitle": "Untertitel ({n} Spur(en))",
    "mi_cat_other": "Sonstiges (Container-Overhead)",
    "mi_estimated": "geschätzt",
    "mi_estimated_hint": "„geschätzt“ = aus Bitrate × Dauer berechnet (kein "
                         "exaktes MKV-Statistik-Tag verfügbar) – kann leicht "
                         "von der tatsächlichen Größe abweichen.",
    "ctx_audio_mode": "Audio-Modus (pro Spur)",
    "ctx_audio_bitrate": "Zielbitrate",
    "ctx_audio_channels": "Zielkanäle",
    "ctx_audio_drc": "Dynamikkompression (DRC)",
    "audio_mode_global": "Global",
    "audio_bitrate_auto": "Automatisch ({kbps} kb/s)",
    "audio_channels_auto": "Automatisch ({ch}ch)",
    "audio_channels_1": "Mono (1ch)",
    "audio_channels_2": "Stereo (2ch)",
    "audio_channels_6": "5.1 (6ch)",
    "drc_off": "Aus",
    # Job-Status
    "status_analyzing": "Analysiere…",
    "status_ready": "Bereit",
    "status_queued": "In Warteschlange",
    "status_running": "Läuft",
    "status_done": "Fertig",
    "status_error": "Fehler",
    "status_skipped": "Übersprungen",
    "status_exists": "Ziel existiert!",
    "status_done_size": "Fertig  {mb:.0f} MB  ({pct:.0f}%)",
    # Audio-Modus
    "lbl_audio_mode": "Audio:",
    "audio_mode_copy": "Kopieren",
    "audio_mode_ac3": "→ AC3",
    "audio_mode_aac": "→ AAC",
    "status_atmos_warn": "Bereit  ⚠ Atmos-Objekte gehen verloren",
    # Zeitanzeige
    "time_job": "Job",
    "time_job_rem": "noch ~{t}",
    "time_total": "Gesamt {t}",
    "time_total_rem": "noch ~{t}",
    "time_done": "Fertig  {done}  Gesamt {total}",
    # Sonstiges
    "audio_none": "Kein Audio",
    "crop_analyzing": "analysiere…",
    "crop_error": "Fehler",
    "crop_sample": "Crop {done}/{total}",
    "encoder_searching": "Suche…",
}

_EN: dict[str, str] = {
    "window_title": _TITLE,
    "lbl_target": "Target resolution:",
    "lbl_crf": "CRF:",
    "lbl_encoder": "Encoder:",
    "lbl_video_mode": "Video:",
    "video_mode_copy": "Copy",
    "lbl_preset": "Preset:",
    "lbl_tune": "Tune:",
    "lbl_outdir": "Output folder:",
    "lbl_name_tag": "Tag:",
    "ph_name_tag": "e.g. MyTag",
    "tt_name_tag": ("Free-form tag appended at the very end of every output "
                    "filename (e.g. encoder/release-group tag)"),
    "tt_preset": ("Speed ↔ Quality (libx265 presets; "
                  "HW encoders mapped accordingly)"),
    "tt_tune": "Content tuning – fully effective only with libx265 (software)",
    "chk_autocrop": "Crop analysis",
    "tt_autocrop": ("Auto-detect black bars (cropdetect); "
                    "off = files imported without crop"),
    "lbl_crop_min": "Min. crop:",
    "tt_crop_min": ("Ignore crop borders smaller than this (pixels per side) "
                    "so e.g. FullHD/4K stays pixel-perfect. 0 = off"),
    "chk_first_crop": "Check only first file for crop",
    "ph_outdir": "(source folder)",
    "drop_hint": "Drop files/folders here or click",
    "drop_scanning": "Scanning folder…",
    "col_file": "File",
    "col_res": "Resolution",
    "col_crop_on": "Crop",
    "col_crop": "Crop value",
    "col_target": "Target resolution",
    "col_hdr": "HDR",
    "col_audio": "Audio",
    "col_crf": "CRF",
    "col_tune": "Tune",
    "col_mono": "B/W",
    "tt_mono": ("Black & white encoding (HEVC Monochrome profile, saves "
               "chroma bits) – only effective with libx265, combinable with "
               "any tune. Pre-selected automatically when crop analysis is "
               "on and the source is detected as grayscale (overridable "
               "here at any time)."),
    "col_encoder": "Encoder",
    "col_preset": "Preset",
    "col_out": "Output",
    "col_status": "Status",
    "chk_log": "Log",
    "tt_log": "Show tool output (ffmpeg, dovi_tool, mkvmerge…)",
    "btn_clear_log": "Clear log",
    "btn_tools_missing": "Download missing tools",
    "btn_tools_update": "Check for tool updates",
    "btn_start": "Start",
    "btn_pause": "Pause",
    "btn_resume": "Resume",
    "tt_pause_unsupported": ("Pause isn't available on Windows "
                             "(no SIGSTOP equivalent for processes)"),
    "btn_stop": "Stop",
    "tools_ok": "All tools found.",
    "tools_missing": "MISSING: {names}",
    "tools_no_dovi": "dovi_tool missing → DV files will be encoded as HDR10.",
    "tools_no_mkv": "mkvmerge missing → DV mux via ffmpeg (no attachments).{hint}",
    "tools_mkv_hint": " (manual: mkvtoolnix.download)",
    "tools_current": "All tools up to date.",
    "tools_searching": "Searching for tool updates…",
    "dlg_updates_title": "Tool updates available",
    "dlg_updates_text": "Updates available:\n{lines}\n\nDownload now?",
    "dlg_dl_fail_title": "Download failed",
    "dlg_dl_fail_text": "{msg}\n\nPlease install the tool manually or try again.",
    "dlg_close_title": "Quit",
    "dlg_close_text": "An encode is still running.",
    "dlg_close_info": "Quit and stop the process, or let it continue in the background?",
    "btn_close_stop": "Quit",
    "btn_close_bg": "Keep running",
    "btn_close_cancel": "Cancel",
    "help_title": "Help / README",
    "help_load_error": "Could not load README.md: {err}",
    "btn_sysinfo": "System Info",
    "sysinfo_title": "System Analysis",
    "sysinfo_os": "Operating system",
    "sysinfo_encoders": "Detected encoders",
    "sysinfo_x265": "x265 version",
    "sysinfo_tools": "External tools",
    "sysinfo_col_tool": "Tool",
    "sysinfo_col_version": "Version",
    "sysinfo_col_path": "Path",
    "sysinfo_col_encoder": "Encoder",
    "sysinfo_col_fps": "Benchmark",
    "sysinfo_pending": "–",
    "sysinfo_running": "running…",
    "sysinfo_run_bench": "Run benchmark",
    "sysinfo_no_ffmpeg": "ffmpeg not found",
    "sysinfo_error": "Error",
    "qc_title": "Quality comparison – {name}",
    "qc_encoder": "Encoder",
    "qc_metrics": "Metrics",
    "qc_metric_tip_vmaf": "VMAF (Video Multimethod Assessment Fusion, 0–100,"
                         " higher = better). Developed by Netflix and trained"
                         " on human ratings — the most reliable indicator of"
                         " perceived quality here, especially for compression"
                         " artifacts. Recommended default for this comparison.",
    "qc_metric_tip_ssim": "SSIM (Structural Similarity, 0–1, higher = better)."
                         " Compares local structure/contrast/luminance instead"
                         " of raw pixel values. Well-established, but"
                         " correlates less well with human perception than"
                         " VMAF, especially for blocking/ringing artifacts.",
    "qc_metric_tip_psnr": "PSNR (Peak Signal-to-Noise Ratio, dB, higher ="
                         " better). A simple pixel-wise difference metric —"
                         " fast to compute, but correlates weakest with"
                         " actually perceived quality of the three. Meant as"
                         " a rough secondary reference, not the main"
                         " decision-making metric.",
    "qc_vmaf_missing": "This ffmpeg lacks libvmaf. For VMAF on Windows: "
                       "re-download tools (full build, needs 7-Zip).",
    "qc_no_metric": "Select at least one metric.",
    "qc_pareto_hint": "★ = not dominated by any other variant (none is both "
                      "smaller and at least as good) — more meaningful than a "
                      "score-per-MB ratio, since the quality curve is not "
                      "linear with file size.",
    "qc_video_only": "Size estimate is video-only (no audio/subtitles).",
    "qc_dblclick_hint": "Double-click a row to play back its sample (the "
                        "original for the reference row). Select multiple "
                        "rows + \"Compare frames\" to view stills side by side.",
    "qc_samples_label": "Samples:",
    "qc_sample_secs_label": "Duration per sample:",
    "qc_variants": "Test variants",
    "qc_resolutions": "Resolutions:",
    "qc_crfs": "CRF values (comma-separated):",
    "qc_tunes": "Tune:",
    "qc_test_monochrome": "Also test as black & white",
    "qc_test_monochrome_tt": ("Doubles the variant matrix: every "
                              "combination is additionally tested with "
                              "B/W encoding enabled (HEVC Monochrome "
                              "profile) – only effective with libx265"),
    "qc_variant_mono": "B/W",
    "qc_count": "{n} variants × {samples} samples of {secs} s",
    "qc_col_variant": "Variant",
    "qc_col_size": "Size (estimated)",
    "qc_col_pct": "% of original",
    "qc_preview_title": "Preview – {name}",
    "qc_preview_missing": "Sample file no longer exists.",
    "qc_play": "▶ Play",
    "qc_pause": "⏸ Pause",
    "qc_compare_btn": "Compare frames",
    "qc_compare_title": "Frame comparison",
    "qc_compare_time": "Second within sample:",
    "qc_compare_refresh": "Refresh",
    "qc_compare_loading": "Loading…",
    "qc_compare_clip_select": "Choose the test clip for this cell (including previous settings)",
    "qc_compare_sample": "Sample:",
    "qc_compare_sample_select": "Switch between the tested sample points (e.g. 20/50/80% of runtime)",
    "qc_compare_sample_n": "Sample {n}",
    "qc_compare_open_window": "Open in window",
    "qc_run_n": "run {n}",
    "qc_original": "Original (reference)",
    "qc_start": "Run test",
    "qc_apply": "Apply",
    "qc_error": "Error",
    "fdlg_files_title": "Select video files",
    "fdlg_files_filter": "Videos (*.mkv *.mp4 *.m4v *.mov *.avi *.ts *.m2ts *.webm);;All (*)",
    "fdlg_folder_title": "…or select folder",
    "fdlg_outdir_title": "Output folder",
    "ctx_reanalyze": "Re-analyze crop for this file",
    "ctx_preview": "Crop preview…",
    "ctx_force": "Force overwrite",
    "ctx_requeue": "Re-queue",
    "ctx_up": "Move up",
    "ctx_down": "Move down",
    "ctx_remove": "Remove from list",
    "ctx_quality": "Quality comparison…",
    "ctx_media_info": "Media info…",
    "ctx_apply_settings": "Apply settings to other rows…",
    "apply_settings_title": "Apply settings – {name}",
    "apply_settings_what": "What to apply:",
    "apply_settings_audio": "Audio selection/mode (track overrides)",
    "apply_settings_audio_tt": ("Matched by track index (1st audio track "
                                "→ 1st audio track etc.); rows with a "
                                "different track count are skipped for audio"),
    "apply_settings_crop": "Crop enabled/disabled",
    "apply_settings_target": "Target resolution",
    "apply_settings_tune": "Tune",
    "apply_settings_crf": "CRF",
    "apply_settings_video_mode": "Video mode (Encode/Copy)",
    "apply_settings_rows": "Apply to these rows:",
    "apply_settings_audio_skipped": ("{n} row(s) had a different audio "
                                     "track count - audio NOT applied there, "
                                     "other settings were."),
    # Media info dialog
    "mi_title": "Media info – {name}",
    "mi_title_compare": "Media info (original vs. result) – {name}",
    "mi_original": "Original",
    "mi_result": "Result",
    "mi_container": "Container",
    "mi_total_size": "Total size",
    "mi_col_stream": "Stream",
    "mi_col_size": "Size",
    "mi_col_pct": "Share",
    "mi_video_label": "Video: {codec} {w}×{h}",
    "mi_audio_label": "Audio #{n}: {codec}{lang} {ch}ch",
    "mi_subtitle_label": "Subtitle: {codec}",
    "mi_other_stream_label": "Other: {codec}",
    "mi_other": "Other (container overhead)",
    "mi_cat_video": "Video",
    "mi_cat_audio": "Audio ({n} track(s))",
    "mi_cat_subtitle": "Subtitles ({n} track(s))",
    "mi_cat_other": "Other (container overhead)",
    "mi_estimated": "estimated",
    "mi_estimated_hint": "“estimated” = calculated from bitrate × duration "
                         "(no exact MKV statistics tag available) — may differ "
                         "slightly from the actual size.",
    "ctx_audio_mode": "Audio mode (per track)",
    "ctx_audio_bitrate": "Target bitrate",
    "ctx_audio_channels": "Target channels",
    "ctx_audio_drc": "Dynamic Range Compression (DRC)",
    "audio_mode_global": "Global",
    "audio_bitrate_auto": "Automatic ({kbps} kb/s)",
    "audio_channels_auto": "Automatic ({ch}ch)",
    "audio_channels_1": "Mono (1ch)",
    "audio_channels_2": "Stereo (2ch)",
    "audio_channels_6": "5.1 (6ch)",
    "drc_off": "Off",
    "status_analyzing": "Analyzing…",
    "status_ready": "Ready",
    "status_queued": "Queued",
    "status_running": "Running",
    "status_done": "Done",
    "status_error": "Error",
    "status_skipped": "Skipped",
    "status_exists": "Target exists!",
    "status_done_size": "Done  {mb:.0f} MB  ({pct:.0f}%)",
    "time_job": "Job",
    "time_job_rem": "~{t} left",
    "time_total": "Total {t}",
    "time_total_rem": "~{t} left",
    "time_done": "Done  {done}  Total {total}",
    "audio_none": "No audio",
    "lbl_audio_mode": "Audio:",
    "audio_mode_copy": "Copy",
    "audio_mode_ac3": "→ AC3",
    "audio_mode_aac": "→ AAC",
    "status_atmos_warn": "Ready  ⚠ Atmos objects will be lost",
    "crop_analyzing": "analyzing…",
    "crop_error": "Error",
    "crop_sample": "Crop {done}/{total}",
    "encoder_searching": "Searching…",
}

_STRINGS: dict[str, dict[str, str]] = {"de": _DE, "en": _EN}


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = lang


def get_lang() -> str:
    return _LANG


def t(key: str, **kwargs: object) -> str:
    s = _STRINGS.get(_LANG, _DE).get(key, _DE.get(key, key))
    return s.format(**kwargs) if kwargs else s


_STATUS_KEYS = {
    "ANALYZING": "status_analyzing",
    "READY":     "status_ready",
    "QUEUED":    "status_queued",
    "RUNNING":   "status_running",
    "DONE":      "status_done",
    "ERROR":     "status_error",
    "SKIPPED":   "status_skipped",
    "EXISTS":    "status_exists",
}


def status_t(status) -> str:
    """Übersetzt einen JobStatus-Enum in den lokalisierten Anzeigetext."""
    return t(_STATUS_KEYS.get(status.name, status.name))
