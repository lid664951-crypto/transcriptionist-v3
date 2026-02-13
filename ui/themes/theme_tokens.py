from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    window_bg: str
    surface_0: str
    surface_1: str
    surface_2: str
    border: str
    border_soft: str
    accent: str
    text_primary: str
    text_secondary: str
    text_muted: str
    success: str
    warning: str
    danger: str
    card_bg: str
    card_hover: str
    card_selected: str
    card_border: str


def get_theme_tokens(is_dark: bool = True) -> ThemeTokens:
    if is_dark:
        return ThemeTokens(
            window_bg="#1E1E1E",
            surface_0="#252526",
            surface_1="#2D2D30",
            surface_2="#333337",
            border="#3F3F46",
            border_soft="#51515B",
            accent="#4EA1FF",
            text_primary="#F3F3F3",
            text_secondary="#C7C7CC",
            text_muted="#9EA0A6",
            success="#57C26F",
            warning="#F0B44D",
            danger="#E26262",
            card_bg="#252930",
            card_hover="#2D333C",
            card_selected="#303B4A",
            card_border="#3A404A",
        )

    return ThemeTokens(
        window_bg="#F3F3F3",
        surface_0="#FFFFFF",
        surface_1="#F7F7F8",
        surface_2="#EFEFF1",
        border="#D8D8DC",
        border_soft="#C6C6CC",
        accent="#2D7FE3",
        text_primary="#1F1F22",
        text_secondary="#4A4C54",
        text_muted="#6F727C",
        success="#2A9E4B",
        warning="#C17C1A",
        danger="#C74444",
        card_bg="#FFFFFF",
        card_hover="#F5F8FD",
        card_selected="#EAF2FF",
        card_border="#D3D9E4",
    )


def build_runtime_token_qss(tokens: ThemeTokens) -> str:
    return f"""
TranscriptionistWindow {{
    background-color: {tokens.window_bg};
    color: {tokens.text_primary};
}}

QWidget {{
    color: {tokens.text_primary};
}}

QLabel {{
    color: {tokens.text_primary};
    background: transparent;
}}

CardWidget,
ElevatedCardWidget,
SimpleCardWidget {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 10px;
}}

BodyLabel {{
    color: {tokens.text_primary};
}}

CaptionLabel {{
    color: {tokens.text_secondary};
}}

BodyLabel#titleBarAppTitle {{
    color: {tokens.text_primary};
    font-size: 12px;
    font-weight: 600;
    padding-left: 6px;
    padding-right: 6px;
    background: transparent;
}}

CaptionLabel#titleBarRealtimeIndexLabel,
CaptionLabel#titleBarBenchmarkGateLabel {{
    font-size: 10px;
    font-weight: 500;
    padding-left: 6px;
    padding-right: 4px;
    background: transparent;
}}

TransparentToolButton#titleBarRealtimeDetailBtn,
TransparentToolButton#titleBarBenchmarkDetailBtn,
TransparentToolButton#titleBarHelpBtn,
TransparentToolButton#titleBarSettingsBtn {{
    border-radius: 6px;
}}

TransparentToolButton#titleBarRealtimeDetailBtn[statusState="running"],
TransparentToolButton#titleBarBenchmarkDetailBtn[statusState="pass"] {{
    color: {tokens.success};
}}

TransparentToolButton#titleBarRealtimeDetailBtn[statusState="pending"] {{
    color: {tokens.warning};
}}

TransparentToolButton#titleBarRealtimeDetailBtn[statusState="error"],
TransparentToolButton#titleBarBenchmarkDetailBtn[statusState="fail"],
TransparentToolButton#titleBarBenchmarkDetailBtn[statusState="error"] {{
    color: {tokens.danger};
}}

TransparentToolButton#titleBarRealtimeDetailBtn[statusState="idle"],
TransparentToolButton#titleBarBenchmarkDetailBtn[statusState="unknown"] {{
    color: {tokens.text_muted};
}}

QWidget#workstationLayout,
QWidget#workstationCenterWidget,
QWidget#resourcePanel,
QWidget#batchCenterPanel {{
    background-color: {tokens.surface_0};
}}

QWidget#workstationMainSplitter::handle {{
    background: {tokens.border};
}}

QFrame#workstationPanelHeader,
QFrame#workstationCenterHeader {{
    background-color: {tokens.surface_1};
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

CaptionLabel#workstationPanelTitle,
CaptionLabel#workstationCenterTitle {{
    color: {tokens.text_secondary};
    font-weight: 600;
    letter-spacing: 0.5px;
}}

TransparentPushButton#workstationFocusLibraryBtn,
TransparentPushButton#workstationFocusWorkbenchBtn {{
    min-width: 24px;
    min-height: 24px;
    border-radius: 6px;
    border: 1px solid transparent;
    background: transparent;
    color: {tokens.text_muted};
    font-size: 16px;
    font-weight: 300;
    padding: 0;
}}

TransparentPushButton#workstationFocusLibraryBtn:hover,
TransparentPushButton#workstationFocusWorkbenchBtn:hover {{
    background-color: {tokens.surface_2};
    border-color: {tokens.border_soft};
    color: {tokens.text_primary};
}}

TransparentPushButton#workstationFocusLibraryBtn:pressed,
TransparentPushButton#workstationFocusWorkbenchBtn:pressed {{
    background-color: {tokens.surface_2};
}}

TransparentPushButton#workstationFocusLibraryBtn[active="true"],
TransparentPushButton#workstationFocusWorkbenchBtn[active="true"] {{
    background-color: {tokens.card_selected};
    border-color: {tokens.border};
    color: {tokens.accent};
}}

QStackedWidget#workstationPanelContent {{
    background-color: {tokens.surface_0};
}}

QTabWidget#resourceTabs::pane,
QTabWidget#batchCenterTabs::pane,
QTabWidget#workstationCenterTabs::pane {{
    border: none;
    background: {tokens.surface_0};
}}

QTabWidget#resourceTabs QTabBar,
QTabWidget#batchCenterTabs QTabBar,
QTabWidget#workstationCenterTabs QTabBar {{
    qproperty-drawBase: 0;
}}

QTabWidget#resourceTabs QTabBar::tab,
QTabWidget#batchCenterTabs QTabBar::tab,
QTabWidget#workstationCenterTabs QTabBar::tab {{
    background: {tokens.surface_1};
    color: {tokens.text_muted};
    min-height: 34px;
    padding: 8px 14px;
    margin-right: 2px;
    border: 1px solid {tokens.border};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}}

QTabWidget#resourceTabs QTabBar::tab:selected,
QTabWidget#batchCenterTabs QTabBar::tab:selected,
QTabWidget#workstationCenterTabs QTabBar::tab:selected {{
    background: {tokens.surface_0};
    color: {tokens.accent};
    border-color: {tokens.border};
}}

QTabWidget#resourceTabs QTabBar::tab:hover:!selected,
QTabWidget#batchCenterTabs QTabBar::tab:hover:!selected,
QTabWidget#workstationCenterTabs QTabBar::tab:hover:!selected {{
    background: {tokens.surface_2};
    color: {tokens.text_secondary};
}}

QWidget#libraryToolbarContainer {{
    background: transparent;
}}

QWidget#libraryToolbarContainer SearchLineEdit,
QWidget#libraryToolbarContainer ComboBox,
QWidget#libraryToolbarContainer PrimaryPushButton,
QWidget#libraryToolbarContainer TransparentToolButton {{
    min-height: 34px;
    max-height: 34px;
}}

QWidget#libraryToolbarContainer SearchLineEdit {{
    padding-left: 10px;
    padding-right: 8px;
}}

QWidget#libraryToolbarContainer ComboBox {{
    padding-left: 10px;
    padding-right: 26px;
}}

QWidget#libraryEmptyDropCard {{
    border: 1px dashed {tokens.border_soft};
    border-radius: 12px;
    background-color: {tokens.surface_1};
}}

QWidget#libraryEmptyDropCard[dragActive="true"] {{
    border: 1px solid {tokens.accent};
    background-color: {tokens.card_selected};
}}

QWidget#libraryEmptyDropIconWrap {{
    border-radius: 34px;
    background-color: {tokens.surface_2};
    border: 1px solid {tokens.border_soft};
}}

SubtitleLabel#libraryEmptyDropTitle {{
    color: {tokens.text_primary};
}}

CaptionLabel#libraryEmptyDropDesc {{
    color: {tokens.text_secondary};
    font-size: 12px;
}}

CaptionLabel#libraryStatusHint,
CaptionLabel#libraryStatusMeta {{
    color: {tokens.text_muted};
}}

QListWidget#aiTranslateJobList {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 8px;
}}

QListWidget#aiTranslateJobList::item {{
    padding: 4px 8px;
    border-radius: 6px;
}}

QListWidget#aiTranslateJobList::item:selected {{
    background-color: {tokens.card_selected};
    color: {tokens.text_primary};
}}

QSplitter#aiTranslateMainSplitter::handle {{
    background: transparent;
}}

QSplitter#aiTranslateMainSplitter::handle:horizontal {{
    width: 8px;
    margin: 10px 2px;
    border-radius: 4px;
    background: {tokens.border_soft};
}}

QSplitter#aiTranslateMainSplitter::handle:horizontal:hover {{
    background: {tokens.accent};
}}

QWidget#aiSearchHeaderContainer {{
    background: transparent;
}}

CaptionLabel#aiSearchHeaderDesc,
CaptionLabel#aiSearchSelectionDesc,
CaptionLabel#aiSearchJobEmptyLabel,
CaptionLabel#aiSearchQueryHint,
CaptionLabel#aiSearchResultHint,
CaptionLabel#aiSearchIndexingLabel,
CaptionLabel#aiTranslateHeaderDesc,
CaptionLabel#aiTranslateLoadMoreHint {{
    color: {tokens.text_muted};
}}

QWidget#aiSearchResultHeader {{
    background: transparent;
}}

QWidget#aiSearchSearchPage,
QScrollArea#aiSearchSearchScroll,
QWidget#aiSearchSearchContent {{
    background: transparent;
    border: none;
}}

CardWidget#aiSearchSelectionCard,
CardWidget#aiSearchJobCard,
CardWidget#aiTranslateLeftCard,
CardWidget#aiTranslateRightCard {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}

QWidget#aiSearchQueryCard,
QWidget#aiSearchQueryCard {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}

QListWidget#aiSearchJobList,
QListWidget#aiSearchResultsList {{
    background: transparent;
    border: none;
}}

TransparentPushButton#aiSearchJobExpandBtn {{
    min-width: 66px;
}}

TransparentPushButton#aiSearchJobClearBtn {{
    min-width: 62px;
}}

QWidget#aiSearchPage ComboBox {{
    min-width: 180px;
}}

QWidget#aiTranslatePage ComboBox {{
    min-height: 34px;
}}

QListWidget#aiSearchResultsList::item {{
    padding: 9px 12px;
    margin: 3px 0;
    border-radius: 8px;
}}

QListWidget#aiSearchResultsList::item:selected {{
    background: {tokens.card_selected};
    color: {tokens.text_primary};
}}

QTreeWidget {{
    border-radius: 8px;
}}

SearchLineEdit,
LineEdit,
ComboBox,
TextEdit,
DoubleSpinBox {{
    border-radius: 8px;
}}

ComboBox {{
    min-width: 88px;
}}

QWidget#libraryToolbarContainer ComboBox {{
    min-height: 30px;
}}

QWidget#aiGenerationPage ScrollArea#aiGenerationScroll,
QWidget#aiGenerationPage QWidget#aiGenerationContent {{
    background: transparent;
    border: none;
}}

QWidget#aiGenerationPage ElevatedCardWidget#aiGenerationInputCard,
QWidget#aiGenerationPage ElevatedCardWidget#aiGenerationParamsCard,
QWidget#aiGenerationPage ElevatedCardWidget#aiGenerationResultCard {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}

TitleLabel#aiGenerationTitle {{
    color: {tokens.text_primary};
    font-weight: 700;
}}

CaptionLabel#aiGenerationSubtitle,
CaptionLabel#aiGenerationPromptHint,
CaptionLabel#aiGenerationStatus {{
    color: {tokens.text_secondary};
}}

SubtitleLabel#aiGenerationInputTitle,
SubtitleLabel#aiGenerationParamsTitle,
BodyLabel#aiGenerationResultLabel {{
    color: {tokens.text_primary};
    font-weight: 600;
}}

BodyLabel#aiGenerationDurationLabel,
BodyLabel#aiGenerationFormatLabel,
BodyLabel#aiGenerationTaskIdLabel {{
    color: {tokens.text_secondary};
}}

CaptionLabel#aiGenerationDurationValue {{
    color: {tokens.text_muted};
}}

TextEdit#aiGenerationPromptEdit,
LineEdit#aiGenerationTaskIdEdit,
ComboBox#aiGenerationFormatCombo {{
    background-color: {tokens.surface_1};
    border: 1px solid {tokens.border};
    color: {tokens.text_primary};
    border-radius: 8px;
}}

LineEdit#aiGenerationTaskIdEdit {{
    color: {tokens.text_secondary};
}}

PrimaryPushButton#aiGenerationGenerateBtn {{
    min-height: 40px;
    border-radius: 8px;
}}

PushButton#aiGenerationPlayBtn,
PushButton#aiGenerationOpenFolderBtn {{
    background-color: {tokens.surface_1};
    border: 1px solid {tokens.border};
    color: {tokens.text_primary};
    border-radius: 8px;
}}

PushButton#aiGenerationPlayBtn:hover,
PushButton#aiGenerationOpenFolderBtn:hover {{
    background-color: {tokens.surface_2};
    border-color: {tokens.border_soft};
}}

PushButton#aiGenerationPlayBtn:pressed,
PushButton#aiGenerationOpenFolderBtn:pressed {{
    background-color: {tokens.card_selected};
}}

ProgressBar#aiGenerationProgress {{
    background-color: {tokens.surface_2};
    border: 1px solid {tokens.border};
    border-radius: 4px;
}}

QWidget#playerBarRoot {{
    background-color: {tokens.surface_1};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}

BodyLabel#playerBarTitle {{
    color: {tokens.text_primary};
    font-weight: 600;
}}

CaptionLabel#playerBarSubtitle,
CaptionLabel#playerBarTime {{
    color: {tokens.text_secondary};
}}

QWidget#playerBarInfo,
QWidget#playerBarProgress {{
    background: transparent;
}}

ToolButton#playerBarPlayBtn {{
    background-color: {tokens.accent};
    border-radius: 20px;
    color: #ffffff;
}}

ToolButton#playerBarPlayBtn:hover {{
    background-color: {tokens.accent};
}}

ToolButton#playerBarPlayBtn:pressed {{
    background-color: {tokens.accent};
}}

QSlider#playerBarProgressSlider::groove:horizontal,
QSlider#playerBarVolumeSlider::groove:horizontal {{
    background: {tokens.border};
    height: 4px;
    border-radius: 2px;
}}

QSlider#playerBarProgressSlider::sub-page:horizontal,
QSlider#playerBarVolumeSlider::sub-page:horizontal {{
    background: {tokens.accent};
    border-radius: 2px;
}}

QSlider#playerBarProgressSlider::handle:horizontal,
QSlider#playerBarVolumeSlider::handle:horizontal {{
    background: {tokens.surface_0};
    border: 1px solid {tokens.accent};
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}

PrimaryPushButton,
PushButton,
TransparentPushButton,
ToolButton,
TransparentToolButton {{
    border-radius: 8px;
}}

QWidget#libraryPage,
QWidget#projectsPage,
QWidget#onlineResourcesPage,
QWidget#tagsPage,
QWidget#aiSearchPage,
QWidget#aiTranslatePage,
QWidget#aiGenerationPage,
QWidget#settingsPage {{
    background-color: {tokens.window_bg};
}}

QWidget#audioFilesPanelRoot {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 10px;
}}

QTreeView#audioFilesView {{
    background: transparent;
    border: none;
    outline: none;
}}

QTreeView#audioFilesView::item {{
    background: transparent;
    border: none;
}}

QTreeView#audioFilesView QHeaderView::section {{
    background-color: {tokens.surface_1};
    color: {tokens.text_secondary};
    border: none;
    border-bottom: 1px solid {tokens.border};
    padding: 8px 10px;
    font-weight: 600;
}}

QTreeView#audioFilesView QScrollBar:vertical,
QTreeView#audioFilesView QScrollBar:horizontal {{
    background: transparent;
}}

QTreeView#audioFilesView QScrollBar::handle:vertical,
QTreeView#audioFilesView QScrollBar::handle:horizontal {{
    background: {tokens.border_soft};
    border-radius: 6px;
}}

QTreeView#audioFilesView QScrollBar::add-line:vertical,
QTreeView#audioFilesView QScrollBar::sub-line:vertical,
QTreeView#audioFilesView QScrollBar::add-line:horizontal,
QTreeView#audioFilesView QScrollBar::sub-line:horizontal {{
    width: 0px;
    height: 0px;
}}
"""
