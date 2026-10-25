"""Main editor shell layout.

Kept separate from editor behavior so the main window remains an integration
controller and the workspace layout can evolve independently.
"""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSplitter, QProgressBar,
    QVBoxLayout, QWidget,
)


def build_editor_layout(window):
    central = QWidget()
    window.setCentralWidget(central)

    root = QVBoxLayout(central)
    root.setContentsMargins(3, 3, 3, 3)
    root.setSpacing(3)

    top = QFrame()
    top.setObjectName("TopBar")
    top.setFixedHeight(34)

    row = QHBoxLayout(top)
    row.setContentsMargins(8, 2, 8, 2)
    row.setSpacing(6)

    brand = QLabel("SKYZEN")
    brand.setObjectName("Brand")
    row.addWidget(brand)

    menu_button = QPushButton("Menu⌄")
    menu_button.setFixedHeight(25)
    menu = QMenu(menu_button)
    window.proxy_action = QAction("Create fast proxies on import", window)
    window.proxy_action.setCheckable(True)
    window.proxy_action.setChecked(bool(window.proxy_enabled))
    window.proxy_action.setToolTip(
        "Create fast 640×360 editing copies in the background on import. Audio is preserved; original files are never changed."
    )
    window.proxy_action.toggled.connect(window._set_proxy_enabled)
    menu.addAction(window.proxy_action)

    # Preview quality is an explicit performance/clarity trade-off. Performance
    # remains the default for CPU-only/low-end PCs; Clear uses original media.
    quality_menu = menu.addMenu("Preview Quality")
    quality_group = QActionGroup(window)
    quality_group.setExclusive(True)
    window.preview_quality_actions = {}
    for quality_name in ("Performance", "Balanced", "Clear"):
        quality_action = QAction(quality_name, window)
        quality_action.setCheckable(True)
        quality_action.setChecked(
            getattr(window, "preview_quality", "Performance") == quality_name
        )
        quality_action.triggered.connect(
            lambda checked=False, name=quality_name: window._set_preview_quality(name)
        )
        quality_group.addAction(quality_action)
        quality_menu.addAction(quality_action)
        window.preview_quality_actions[quality_name] = quality_action

    build_proxies_action = QAction("Build proxies for current media bin", window)
    build_proxies_action.triggered.connect(window._build_proxies_for_current_bin)
    menu.addAction(build_proxies_action)
    menu_button.setMenu(menu)
    row.addWidget(menu_button)

    settings_button = QPushButton("⚙ Settings")
    settings_button.setObjectName("SettingsButton")
    settings_button.setFixedHeight(25)
    settings_button.setToolTip("Customize timeline zoom, scrolling and preview performance")
    settings_button.clicked.connect(window.open_settings_dialog)
    row.addWidget(settings_button)

    saved = QLabel("●  Auto saved: --:--:--")
    saved.setObjectName("Saved")
    window.saved_label = saved
    row.addWidget(saved)

    row.addStretch()

    _proj_name = getattr(window, "root_dir", None)
    _proj_name = _proj_name.name if _proj_name is not None else "Untitled"
    window.project_name_label = QLabel(_proj_name)
    window.project_name_label.setObjectName("ProjectName")
    row.addWidget(window.project_name_label)

    row.addStretch()

    window.status_label = QLabel("Basic editing · 30 FPS")
    window.status_label.setStyleSheet("color:#7F8A9A; font-size:10px;")
    window.status_label.setMinimumWidth(115)
    row.addWidget(window.status_label)

    window.proxy_progress = QProgressBar()
    window.proxy_progress.setRange(0, 0)
    window.proxy_progress.setTextVisible(False)
    window.proxy_progress.setFixedSize(48, 7)
    window.proxy_progress.setStyleSheet(
        "QProgressBar{background:#252525;border:0;border-radius:3px;}"
        "QProgressBar::chunk{background:#00D8E8;border-radius:3px;}"
    )
    window.proxy_progress.hide()
    row.addWidget(window.proxy_progress)

    export_button = QPushButton("Export")
    export_button.setObjectName("Export")
    export_button.setFixedHeight(25)
    export_button.clicked.connect(window.open_export_dialog)
    row.addWidget(export_button)

    root.addWidget(top)

    # ----------------------------------------------------------
    # Horizontal splitter: left / player / inspector
    # ----------------------------------------------------------
    upper = QSplitter(Qt.Orientation.Horizontal)
    upper.setChildrenCollapsible(False)

    upper.addWidget(window.left)
    upper.addWidget(window.player)
    upper.addWidget(window.inspector)

    window.left.setMinimumWidth(220)
    window.player.setMinimumWidth(280)
    window.inspector.setMinimumWidth(250)
    upper.setHandleWidth(5)

    upper.setSizes([300, 630, 320])
    upper.setStretchFactor(0, 0)
    upper.setStretchFactor(1, 1)
    upper.setStretchFactor(2, 0)

    # ----------------------------------------------------------
    # Vertical splitter: upper workspace / timeline
    # THIS is what makes the timeline freely resizable in Y.
    # ----------------------------------------------------------
    workspace_splitter = QSplitter(Qt.Orientation.Vertical)
    workspace_splitter.setChildrenCollapsible(False)
    workspace_splitter.addWidget(upper)
    workspace_splitter.addWidget(window.timeline)

    # Safe minimums prevent panels from collapsing into each other.
    upper.setMinimumHeight(220)
    window.timeline.setMinimumHeight(190)

    workspace_splitter.setHandleWidth(5)
    workspace_splitter.setSizes([350, 350])
    workspace_splitter.setStretchFactor(0, 1)
    workspace_splitter.setStretchFactor(1, 1)

    root.addWidget(workspace_splitter, 1)

    # Connections
    # ----------------------------------------------------------
    # Keep the working LeftPanel untouched. Its '+' button emits
    # (path, media_kind). Route that through a small integration
    # slot so the main window validates the payload before the
    # timeline receives it.
    window.left.preview_requested.connect(
        window.player.show_asset
    )
    window.left.add_requested.connect(
        window._on_media_add_requested
    )
    window.left.add_tool_requested.connect(window._on_tool_add_requested)

    # Timeline clip click -> player.
    # Inspector first: capture the selected clip model before the player
    # switches/refreshes the project preview in response to the same click.
    window.timeline.clip_selected.connect(window.inspector.load_selected_clip)
    window.timeline.clip_selected.connect(
        window.player.show_timeline_clip
    )
    window.timeline.selection_cleared.connect(window.inspector.clear_selection)

    # Timeline playhead -> player seek.
    window.timeline.time_changed.connect(
        window.player.seek_timeline
    )

