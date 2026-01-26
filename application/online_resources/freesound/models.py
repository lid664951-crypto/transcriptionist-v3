"""
Freesound Data Models

Dataclasses and enums for Freesound API integration.
Based on Freesound API v2 documentation: https://freesound.org/docs/api/
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any
from datetime import datetime


class FreesoundLicense(Enum):
    """Creative Commons license types used by Freesound."""
    
    CC0 = "Creative Commons 0"
    CC_BY = "Attribution"
    CC_BY_NC = "Attribution NonCommercial"
    CC_BY_SA = "Attribution ShareAlike"
    CC_BY_NC_SA = "Attribution NonCommercial ShareAlike"
    SAMPLING_PLUS = "Sampling+"
    
    @property
    def allows_commercial(self) -> bool:
        """Check if license allows commercial use."""
        return self in (
            FreesoundLicense.CC0,
            FreesoundLicense.CC_BY,
            FreesoundLicense.CC_BY_SA,
        )
    
    @property
    def requires_attribution(self) -> bool:
        """Check if license requires attribution."""
        return self != FreesoundLicense.CC0
    
    @classmethod
    def from_string(cls, license_str: str) -> 'FreesoundLicense':
        """Parse license string from API response."""
        license_lower = license_str.lower()
        if 'creative commons 0' in license_lower or 'cc0' in license_lower:
            return cls.CC0
        elif 'noncommercial' in license_lower and 'sharealike' in license_lower:
            return cls.CC_BY_NC_SA
        elif 'noncommercial' in license_lower:
            return cls.CC_BY_NC
        elif 'sharealike' in license_lower:
            return cls.CC_BY_SA
        elif 'attribution' in license_lower:
            return cls.CC_BY
        elif 'sampling' in license_lower:
            return cls.SAMPLING_PLUS
        return cls.CC_BY  # Default


# License information for UI display
LICENSE_INFO: Dict[FreesoundLicense, Dict[str, Any]] = {
    FreesoundLicense.CC0: {
        'name': 'CC0 (Public Domain)',
        'name_zh': 'CC0 (公共领域)',
        'commercial': True,
        'attribution': False,
        'description': 'No rights reserved. Free for any use.',
        'description_zh': '无版权保留，可自由用于任何用途。',
        'color': '#10B981',  # Green
        'icon': 'cc-zero',
    },
    FreesoundLicense.CC_BY: {
        'name': 'CC BY (Attribution)',
        'name_zh': 'CC BY (署名)',
        'commercial': True,
        'attribution': True,
        'description': 'Free for commercial use with attribution.',
        'description_zh': '可商用，需标注原作者。',
        'color': '#3B82F6',  # Blue
        'icon': 'cc-by',
    },
    FreesoundLicense.CC_BY_NC: {
        'name': 'CC BY-NC (NonCommercial)',
        'name_zh': 'CC BY-NC (非商业)',
        'commercial': False,
        'attribution': True,
        'description': 'Non-commercial use only with attribution.',
        'description_zh': '仅限非商业使用，需标注原作者。',
        'color': '#EF4444',  # Red
        'icon': 'cc-by-nc',
    },
    FreesoundLicense.CC_BY_SA: {
        'name': 'CC BY-SA (ShareAlike)',
        'name_zh': 'CC BY-SA (相同方式共享)',
        'commercial': True,
        'attribution': True,
        'description': 'Commercial use allowed. Derivatives must use same license.',
        'description_zh': '可商用，衍生作品需使用相同协议。',
        'color': '#8B5CF6',  # Purple
        'icon': 'cc-by-sa',
    },
    FreesoundLicense.CC_BY_NC_SA: {
        'name': 'CC BY-NC-SA',
        'name_zh': 'CC BY-NC-SA (非商业-相同方式共享)',
        'commercial': False,
        'attribution': True,
        'description': 'Non-commercial only. Derivatives must use same license.',
        'description_zh': '仅限非商业使用，衍生作品需使用相同协议。',
        'color': '#F59E0B',  # Orange
        'icon': 'cc-by-nc-sa',
    },
    FreesoundLicense.SAMPLING_PLUS: {
        'name': 'Sampling+',
        'name_zh': 'Sampling+ (采样许可)',
        'commercial': True,
        'attribution': True,
        'description': 'Sampling and remixing allowed.',
        'description_zh': '允许采样和混音使用。',
        'color': '#6366F1',  # Indigo
        'icon': 'sampling-plus',
    },
}


@dataclass
class FreesoundPreview:
    """Preview URLs for a Freesound sound."""
    
    preview_hq_mp3: str = ""
    preview_lq_mp3: str = ""
    preview_hq_ogg: str = ""
    preview_lq_ogg: str = ""
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'FreesoundPreview':
        """Create from API response dict."""
        return cls(
            preview_hq_mp3=data.get('preview-hq-mp3', ''),
            preview_lq_mp3=data.get('preview-lq-mp3', ''),
            preview_hq_ogg=data.get('preview-hq-ogg', ''),
            preview_lq_ogg=data.get('preview-lq-ogg', ''),
        )
    
    @property
    def best_preview(self) -> str:
        """Get best available preview URL."""
        return self.preview_hq_mp3 or self.preview_hq_ogg or self.preview_lq_mp3 or self.preview_lq_ogg


@dataclass
class FreesoundAnalysis:
    """Audio analysis data from Freesound."""
    
    loudness: Optional[float] = None
    dynamic_range: Optional[float] = None
    spectral_centroid: Optional[float] = None
    spectral_complexity: Optional[float] = None
    pitch: Optional[float] = None
    pitch_confidence: Optional[float] = None
    bpm: Optional[float] = None
    key: Optional[str] = None
    scale: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FreesoundAnalysis':
        """Create from API analysis response."""
        lowlevel = data.get('lowlevel', {})
        rhythm = data.get('rhythm', {})
        tonal = data.get('tonal', {})
        
        return cls(
            loudness=lowlevel.get('average_loudness'),
            dynamic_range=lowlevel.get('dynamic_complexity'),
            spectral_centroid=lowlevel.get('spectral_centroid', {}).get('mean'),
            spectral_complexity=lowlevel.get('spectral_complexity', {}).get('mean'),
            pitch=lowlevel.get('pitch', {}).get('mean'),
            pitch_confidence=lowlevel.get('pitch_instantaneous_confidence', {}).get('mean'),
            bpm=rhythm.get('bpm'),
            key=tonal.get('key_key'),
            scale=tonal.get('key_scale'),
        )


@dataclass
class FreesoundSound:
    """
    Represents a sound from Freesound.org.
    
    Maps to the Freesound API sound resource.
    """
    
    id: int
    name: str
    description: str
    username: str
    license: str
    license_url: str
    duration: float
    channels: int
    samplerate: int
    bitdepth: int
    bitrate: int
    filesize: int
    type: str  # wav, mp3, flac, ogg, aiff
    tags: List[str] = field(default_factory=list)
    avg_rating: float = 0.0
    num_ratings: int = 0
    num_downloads: int = 0
    created: Optional[datetime] = None
    previews: Optional[FreesoundPreview] = None
    download_url: str = ""
    analysis: Optional[FreesoundAnalysis] = None
    
    # Translated fields (populated by AI translation)
    name_zh: Optional[str] = None
    description_zh: Optional[str] = None
    tags_zh: Optional[List[str]] = None
    
    @property
    def license_type(self) -> FreesoundLicense:
        """Get parsed license type."""
        return FreesoundLicense.from_string(self.license)
    
    @property
    def license_info(self) -> Dict[str, Any]:
        """Get license display information."""
        return LICENSE_INFO.get(self.license_type, LICENSE_INFO[FreesoundLicense.CC_BY])
    
    @property
    def allows_commercial(self) -> bool:
        """Check if sound can be used commercially."""
        return self.license_type.allows_commercial
    
    @property
    def requires_attribution(self) -> bool:
        """Check if attribution is required."""
        return self.license_type.requires_attribution
    
    @property
    def attribution_text(self) -> str:
        """Generate attribution text for this sound."""
        return f'"{self.name}" by {self.username} via Freesound.org, licensed under {self.license}'
    
    @property
    def duration_formatted(self) -> str:
        """Format duration as MM:SS or HH:MM:SS."""
        total_seconds = int(self.duration)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
    
    @property
    def filesize_formatted(self) -> str:
        """Format file size in human readable form."""
        size = self.filesize
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'FreesoundSound':
        """Create FreesoundSound from API response dict."""
        previews = None
        if 'previews' in data:
            previews = FreesoundPreview.from_dict(data['previews'])
        
        created = None
        if 'created' in data:
            try:
                created = datetime.fromisoformat(data['created'].replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass
        
        return cls(
            id=data.get('id', 0),
            name=data.get('name', ''),
            description=data.get('description', ''),
            username=data.get('username', ''),
            license=data.get('license', ''),
            license_url=data.get('license_url', data.get('license', '')),
            duration=data.get('duration', 0.0),
            channels=data.get('channels', 1),
            samplerate=data.get('samplerate', 44100),
            bitdepth=data.get('bitdepth', 16),
            bitrate=data.get('bitrate', 0),
            filesize=data.get('filesize', 0),
            type=data.get('type', 'wav'),
            tags=data.get('tags', []),
            avg_rating=data.get('avg_rating', 0.0),
            num_ratings=data.get('num_ratings', 0),
            num_downloads=data.get('num_downloads', 0),
            created=created,
            previews=previews,
            download_url=data.get('download', ''),
        )


@dataclass
class FreesoundSearchOptions:
    """Options for Freesound search queries."""
    
    query: str
    page: int = 1
    page_size: int = 20
    sort: str = 'score'  # score, rating_desc, downloads_desc, created_desc
    
    # Filters
    duration_min: Optional[float] = None
    duration_max: Optional[float] = None
    license_types: Optional[List[str]] = None
    file_types: Optional[List[str]] = None
    min_rating: Optional[float] = None
    tags: Optional[List[str]] = None
    channels: Optional[int] = None
    samplerate: Optional[int] = None
    
    def build_filter_string(self) -> str:
        """Build Freesound API filter string."""
        filters = []
        
        if self.duration_min is not None or self.duration_max is not None:
            min_dur = self.duration_min or 0
            max_dur = self.duration_max or '*'
            filters.append(f"duration:[{min_dur} TO {max_dur}]")
        
        if self.license_types:
            license_filter = ' OR '.join(f'"{lt}"' for lt in self.license_types)
            filters.append(f"license:({license_filter})")
        
        if self.file_types:
            type_filter = ' OR '.join(self.file_types)
            filters.append(f"type:({type_filter})")
        
        if self.min_rating is not None:
            filters.append(f"avg_rating:[{self.min_rating} TO 5]")
        
        if self.tags:
            for tag in self.tags:
                filters.append(f"tag:{tag}")
        
        if self.channels is not None:
            filters.append(f"channels:{self.channels}")
        
        if self.samplerate is not None:
            filters.append(f"samplerate:{self.samplerate}")
        
        return ' AND '.join(filters) if filters else ''


@dataclass
class FreesoundSearchResult:
    """Result of a Freesound search query."""
    
    count: int
    results: List[FreesoundSound]
    next_page: Optional[str] = None
    previous_page: Optional[str] = None
    current_page: int = 1
    total_pages: int = 1
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any], page_size: int = 20) -> 'FreesoundSearchResult':
        """Create from API search response."""
        count = data.get('count', 0)
        results = [
            FreesoundSound.from_api_response(sound_data)
            for sound_data in data.get('results', [])
        ]
        
        # Calculate pagination
        total_pages = (count + page_size - 1) // page_size if count > 0 else 1
        
        # Extract current page from next/previous URLs
        next_url = data.get('next')
        prev_url = data.get('previous')
        current_page = 1
        
        if prev_url:
            # If there's a previous page, we're at least on page 2
            current_page = 2
            if next_url:
                # If there's also a next page, calculate from total
                current_page = (total_pages + 1) // 2  # Rough estimate
        
        return cls(
            count=count,
            results=results,
            next_page=next_url,
            previous_page=prev_url,
            current_page=current_page,
            total_pages=total_pages,
        )


@dataclass
class FreesoundDownloadItem:
    """Represents a download queue item."""
    
    sound: FreesoundSound
    status: str = 'pending'  # pending, downloading, completed, failed, cancelled
    progress: float = 0.0
    local_path: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    @property
    def is_active(self) -> bool:
        """Check if download is in progress."""
        return self.status in ('pending', 'downloading')
    
    @property
    def is_complete(self) -> bool:
        """Check if download finished successfully."""
        return self.status == 'completed'
    
    @property
    def is_failed(self) -> bool:
        """Check if download failed."""
        return self.status == 'failed'


@dataclass
class FreesoundSettings:
    """User settings for Freesound integration."""
    
    api_token: str = ""
    download_path: str = ""
    auto_add_to_library: bool = True
    auto_translate_and_rename: bool = True
    keep_original_name: bool = False
    show_license_confirm: bool = True
    auto_translate_search: bool = True
    auto_translate_results: bool = True
    page_size: int = 20
    max_concurrent_downloads: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'api_token': self.api_token,
            'download_path': self.download_path,
            'auto_add_to_library': self.auto_add_to_library,
            'auto_translate_and_rename': self.auto_translate_and_rename,
            'keep_original_name': self.keep_original_name,
            'show_license_confirm': self.show_license_confirm,
            'auto_translate_search': self.auto_translate_search,
            'auto_translate_results': self.auto_translate_results,
            'page_size': self.page_size,
            'max_concurrent_downloads': self.max_concurrent_downloads,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FreesoundSettings':
        """Create from dictionary."""
        return cls(
            api_token=data.get('api_token', ''),
            download_path=data.get('download_path', ''),
            auto_add_to_library=data.get('auto_add_to_library', True),
            auto_translate_and_rename=data.get('auto_translate_and_rename', True),
            keep_original_name=data.get('keep_original_name', False),
            show_license_confirm=data.get('show_license_confirm', True),
            auto_translate_search=data.get('auto_translate_search', True),
            auto_translate_results=data.get('auto_translate_results', True),
            page_size=data.get('page_size', 20),
            max_concurrent_downloads=data.get('max_concurrent_downloads', 3),
        )
