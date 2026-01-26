"""
Freesound License Manager

Handles license tracking, attribution generation, and compliance checking
for sounds downloaded from Freesound.org.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from .models import FreesoundSound, FreesoundLicense, LICENSE_INFO

logger = logging.getLogger(__name__)


@dataclass
class LicenseRecord:
    """
    Record of a downloaded sound's license information.
    
    Used for tracking attribution requirements and compliance.
    """
    
    freesound_id: int
    sound_name: str
    username: str
    license_type: FreesoundLicense
    license_url: str
    download_date: datetime
    local_path: str
    freesound_url: str = ""
    
    @property
    def requires_attribution(self) -> bool:
        """Check if this sound requires attribution."""
        return self.license_type.requires_attribution
    
    @property
    def allows_commercial(self) -> bool:
        """Check if this sound allows commercial use."""
        return self.license_type.allows_commercial
    
    @property
    def attribution_text(self) -> str:
        """Generate attribution text for this sound."""
        return (
            f'"{self.sound_name}" by {self.username} '
            f'via Freesound.org ({self.freesound_url}), '
            f'licensed under {self.license_type.value}'
        )
    
    @property
    def attribution_html(self) -> str:
        """Generate HTML attribution for this sound."""
        return (
            f'<a href="{self.freesound_url}">"{self.sound_name}"</a> by '
            f'<a href="https://freesound.org/people/{self.username}/">{self.username}</a>, '
            f'licensed under <a href="{self.license_url}">{self.license_type.value}</a>'
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'freesound_id': self.freesound_id,
            'sound_name': self.sound_name,
            'username': self.username,
            'license_type': self.license_type.value,
            'license_url': self.license_url,
            'download_date': self.download_date.isoformat(),
            'local_path': self.local_path,
            'freesound_url': self.freesound_url,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LicenseRecord':
        """Create from dictionary."""
        return cls(
            freesound_id=data['freesound_id'],
            sound_name=data['sound_name'],
            username=data['username'],
            license_type=FreesoundLicense.from_string(data['license_type']),
            license_url=data['license_url'],
            download_date=datetime.fromisoformat(data['download_date']),
            local_path=data['local_path'],
            freesound_url=data.get('freesound_url', ''),
        )
    
    @classmethod
    def from_sound(cls, sound: FreesoundSound, local_path: str) -> 'LicenseRecord':
        """Create from FreesoundSound object."""
        return cls(
            freesound_id=sound.id,
            sound_name=sound.name,
            username=sound.username,
            license_type=sound.license_type,
            license_url=sound.license_url,
            download_date=datetime.now(),
            local_path=local_path,
            freesound_url=f"https://freesound.org/sounds/{sound.id}/",
        )


class LicenseManager:
    """
    Manages license records for downloaded Freesound sounds.
    
    Features:
    - Track all downloaded sounds and their licenses
    - Generate attribution reports
    - Check commercial use compliance
    - Export attribution files
    """
    
    def __init__(self, storage_path: Path):
        """
        Initialize license manager.
        
        Args:
            storage_path: Path to store license records
        """
        self.storage_path = storage_path
        self._records: Dict[int, LicenseRecord] = {}
        self._load_records()
    
    def _load_records(self) -> None:
        """Load license records from storage."""
        if not self.storage_path.exists():
            return
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for record_data in data.get('records', []):
                record = LicenseRecord.from_dict(record_data)
                self._records[record.freesound_id] = record
            
            logger.info(f"Loaded {len(self._records)} license records")
        
        except Exception as e:
            logger.error(f"Failed to load license records: {e}")
    
    def _save_records(self) -> None:
        """Save license records to storage."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'version': '1.0',
                'updated': datetime.now().isoformat(),
                'records': [r.to_dict() for r in self._records.values()],
            }
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Saved {len(self._records)} license records")
        
        except Exception as e:
            logger.error(f"Failed to save license records: {e}")
    
    def add_record(self, sound: FreesoundSound, local_path: str) -> LicenseRecord:
        """
        Add a license record for a downloaded sound.
        
        Args:
            sound: FreesoundSound object
            local_path: Path where the sound was saved
        
        Returns:
            Created LicenseRecord
        """
        record = LicenseRecord.from_sound(sound, local_path)
        self._records[sound.id] = record
        self._save_records()
        
        logger.info(f"Added license record for sound {sound.id}")
        return record
    
    def get_record(self, freesound_id: int) -> Optional[LicenseRecord]:
        """
        Get license record by Freesound ID.
        
        Args:
            freesound_id: Freesound sound ID
        
        Returns:
            LicenseRecord if found, None otherwise
        """
        return self._records.get(freesound_id)
    
    def get_record_by_path(self, local_path: str) -> Optional[LicenseRecord]:
        """
        Get license record by local file path.
        
        Args:
            local_path: Local file path
        
        Returns:
            LicenseRecord if found, None otherwise
        """
        for record in self._records.values():
            if record.local_path == local_path:
                return record
        return None
    
    def remove_record(self, freesound_id: int) -> bool:
        """
        Remove a license record.
        
        Args:
            freesound_id: Freesound sound ID
        
        Returns:
            True if removed, False if not found
        """
        if freesound_id in self._records:
            del self._records[freesound_id]
            self._save_records()
            return True
        return False
    
    @property
    def all_records(self) -> List[LicenseRecord]:
        """Get all license records."""
        return list(self._records.values())
    
    @property
    def records_requiring_attribution(self) -> List[LicenseRecord]:
        """Get records that require attribution."""
        return [r for r in self._records.values() if r.requires_attribution]
    
    @property
    def commercial_safe_records(self) -> List[LicenseRecord]:
        """Get records that allow commercial use."""
        return [r for r in self._records.values() if r.allows_commercial]
    
    @property
    def non_commercial_records(self) -> List[LicenseRecord]:
        """Get records that don't allow commercial use."""
        return [r for r in self._records.values() if not r.allows_commercial]
    
    def check_commercial_compliance(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        Check if a set of files can be used commercially.
        
        Args:
            file_paths: List of local file paths to check
        
        Returns:
            Compliance report dictionary
        """
        compliant = []
        non_compliant = []
        unknown = []
        
        for path in file_paths:
            record = self.get_record_by_path(path)
            if record is None:
                unknown.append(path)
            elif record.allows_commercial:
                compliant.append(record)
            else:
                non_compliant.append(record)
        
        return {
            'is_compliant': len(non_compliant) == 0,
            'compliant_count': len(compliant),
            'non_compliant_count': len(non_compliant),
            'unknown_count': len(unknown),
            'compliant': compliant,
            'non_compliant': non_compliant,
            'unknown': unknown,
        }
    
    def generate_attribution_text(
        self,
        file_paths: Optional[List[str]] = None,
    ) -> str:
        """
        Generate attribution text for sounds.
        
        Args:
            file_paths: Optional list of file paths to include.
                       If None, includes all records requiring attribution.
        
        Returns:
            Attribution text
        """
        if file_paths is None:
            records = self.records_requiring_attribution
        else:
            records = []
            for path in file_paths:
                record = self.get_record_by_path(path)
                if record and record.requires_attribution:
                    records.append(record)
        
        if not records:
            return "No attribution required."
        
        lines = ["Sound Credits:", ""]
        for record in records:
            lines.append(f"• {record.attribution_text}")
        
        return '\n'.join(lines)
    
    def generate_attribution_html(
        self,
        file_paths: Optional[List[str]] = None,
    ) -> str:
        """
        Generate HTML attribution for sounds.
        
        Args:
            file_paths: Optional list of file paths to include.
        
        Returns:
            HTML attribution
        """
        if file_paths is None:
            records = self.records_requiring_attribution
        else:
            records = []
            for path in file_paths:
                record = self.get_record_by_path(path)
                if record and record.requires_attribution:
                    records.append(record)
        
        if not records:
            return "<p>No attribution required.</p>"
        
        html_parts = ["<h3>Sound Credits</h3>", "<ul>"]
        for record in records:
            html_parts.append(f"<li>{record.attribution_html}</li>")
        html_parts.append("</ul>")
        
        return '\n'.join(html_parts)
    
    def export_attribution_file(
        self,
        output_path: Path,
        file_paths: Optional[List[str]] = None,
        format: str = 'txt',
    ) -> None:
        """
        Export attribution to a file.
        
        Args:
            output_path: Path to save the attribution file
            file_paths: Optional list of file paths to include
            format: Output format ('txt', 'html', 'json')
        """
        if format == 'txt':
            content = self.generate_attribution_text(file_paths)
        elif format == 'html':
            content = self.generate_attribution_html(file_paths)
        elif format == 'json':
            if file_paths is None:
                records = self.records_requiring_attribution
            else:
                records = []
                for path in file_paths:
                    record = self.get_record_by_path(path)
                    if record:
                        records.append(record)
            
            content = json.dumps(
                [r.to_dict() for r in records],
                ensure_ascii=False,
                indent=2,
            )
        else:
            raise ValueError(f"Unknown format: {format}")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Exported attribution to {output_path}")
    
    def get_license_summary(self) -> Dict[str, int]:
        """
        Get summary of license types in the collection.
        
        Returns:
            Dictionary mapping license type to count
        """
        summary: Dict[str, int] = {}
        for record in self._records.values():
            license_name = record.license_type.value
            summary[license_name] = summary.get(license_name, 0) + 1
        return summary
