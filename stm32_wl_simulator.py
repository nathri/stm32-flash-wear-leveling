#!/usr/bin/env python3
"""
STM32 Flash Wear-Leveling Simulator
=====================================
A comprehensive simulator for testing wear-leveling drivers on STM32 microcontrollers.
Supports fault injection (power cuts), multiple MCU targets, and both buggy and fixed versions.

Author: nathri (enhanced by AI)
Usage: python stm32_wl_simulator.py --mcu STM32F401 --scenario stress --faults 100
"""

import argparse
import copy
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple, Callable
import hashlib


# =============================================================================
# MCU Hardware Database
# =============================================================================

@dataclass
class FlashSector:
    """Represents a single Flash sector."""
    name: str
    base_addr: int
    size: int
    number: int


@dataclass
class MCUConfig:
    """Complete Flash configuration for an STM32 MCU."""
    name: str
    flash_size: int
    sectors: List[FlashSector]
    program_unit: int = 4          # bytes per program operation
    erase_time_16k: float = 0.25   # seconds (typical)
    erase_time_64k: float = 0.5
    erase_time_128k: float = 1.0
    erase_time_256k: float = 2.0
    program_time: float = 0.0001   # seconds per word (typical)
    has_cache: bool = False
    cache_flush_needed: bool = False
    dual_bank: bool = False
    voltage_min: float = 1.8
    voltage_max: float = 3.6
    psize_valid: List[int] = field(default_factory=lambda: [1, 2, 4])  # x8, x16, x32


MCU_DATABASE = {
    "STM32F401": MCUConfig(
        name="STM32F401RE",
        flash_size=256 * 1024,
        sectors=[
            FlashSector("Sector 0", 0x0800_0000, 16 * 1024, 0),
            FlashSector("Sector 1", 0x0800_4000, 16 * 1024, 1),
            FlashSector("Sector 2", 0x0800_8000, 16 * 1024, 2),
            FlashSector("Sector 3", 0x0800_C000, 16 * 1024, 3),
            FlashSector("Sector 4", 0x0801_0000, 64 * 1024, 4),
            FlashSector("Sector 5", 0x0802_0000, 128 * 1024, 5),
        ],
        program_unit=4,
        erase_time_16k=0.25,
        erase_time_64k=0.5,
        erase_time_128k=1.0,
        has_cache=True,
        cache_flush_needed=True,
    ),
    "STM32F767_DUAL": MCUConfig(
        name="STM32F767ZI (Dual-Bank)",
        flash_size=1024 * 1024,
        sectors=[
            # Bank 1
            FlashSector("Sector 0", 0x0800_0000, 16 * 1024, 0),
            FlashSector("Sector 1", 0x0800_4000, 16 * 1024, 1),
            FlashSector("Sector 2", 0x0800_8000, 16 * 1024, 2),
            FlashSector("Sector 3", 0x0800_C000, 16 * 1024, 3),
            FlashSector("Sector 4", 0x0801_0000, 64 * 1024, 4),
            FlashSector("Sector 5", 0x0802_0000, 128 * 1024, 5),
            FlashSector("Sector 6", 0x0804_0000, 128 * 1024, 6),
            FlashSector("Sector 7", 0x0806_0000, 128 * 1024, 7),
            # Bank 2 (gap for sectors 8-11 in dual-bank mode)
            FlashSector("Sector 12", 0x0808_0000, 16 * 1024, 12),
            FlashSector("Sector 13", 0x0808_4000, 16 * 1024, 13),
            FlashSector("Sector 14", 0x0808_8000, 16 * 1024, 14),
            FlashSector("Sector 15", 0x0808_C000, 16 * 1024, 15),
            FlashSector("Sector 16", 0x0809_0000, 64 * 1024, 16),
            FlashSector("Sector 17", 0x080A_0000, 128 * 1024, 17),
            FlashSector("Sector 18", 0x080C_0000, 128 * 1024, 18),
            FlashSector("Sector 19", 0x080E_0000, 128 * 1024, 19),
        ],
        program_unit=4,
        erase_time_16k=0.2,
        erase_time_64k=0.4,
        erase_time_128k=0.8,
        erase_time_256k=1.5,
        has_cache=True,
        cache_flush_needed=True,
        dual_bank=True,
    ),
    "STM32F767_SINGLE": MCUConfig(
        name="STM32F767ZI (Single-Bank)",
        flash_size=1024 * 1024,
        sectors=[
            FlashSector("Sector 0", 0x0800_0000, 32 * 1024, 0),
            FlashSector("Sector 1", 0x0800_8000, 32 * 1024, 1),
            FlashSector("Sector 2", 0x0801_0000, 32 * 1024, 2),
            FlashSector("Sector 3", 0x0801_8000, 32 * 1024, 3),
            FlashSector("Sector 4", 0x0802_0000, 128 * 1024, 4),
            FlashSector("Sector 5", 0x0804_0000, 256 * 1024, 5),
            FlashSector("Sector 6", 0x0808_0000, 256 * 1024, 6),
            FlashSector("Sector 7", 0x080C_0000, 256 * 1024, 7),
        ],
        program_unit=4,
        erase_time_16k=0.2,
        erase_time_64k=0.4,
        erase_time_128k=0.8,
        erase_time_256k=1.5,
        has_cache=True,
        cache_flush_needed=True,
        dual_bank=False,
    ),
    "STM32L476": MCUConfig(
        name="STM32L476RG",
        flash_size=1024 * 1024,
        sectors=[
            FlashSector("Page 0", 0x0800_0000, 2 * 1024, 0),
            FlashSector("Page 1", 0x0800_0800, 2 * 1024, 1),
            FlashSector("Page 2", 0x0800_1000, 2 * 1024, 2),
            FlashSector("Page 3", 0x0800_1800, 2 * 1024, 3),
            # ... (simplified, would continue to 255 pages for 512KB)
        ],
        program_unit=8,  # 64-bit ECC on L4
        erase_time_16k=0.025,  # Much faster on L4
        has_cache=False,
        cache_flush_needed=False,
        dual_bank=True,
    ),
}


# =============================================================================
# Flash Memory Emulation
# =============================================================================

class FlashError(Exception):
    """Base exception for Flash operations."""
    pass


class FlashWriteError(FlashError):
    """Raised when a write operation fails."""
    pass


class FlashEraseError(FlashError):
    """Raised when an erase operation fails."""
    pass


class FlashMemory:
    """
    Emulates STM32 Flash memory at byte level.
    - Unprogrammed bytes = 0xFF
    - Programming can only clear bits (1 -> 0), never set them (0 -> 1)
    - Erase resets entire sector to 0xFF
    - Tracks erase counts per sector
    """

    def __init__(self, mcu_config: MCUConfig):
        self.mcu = mcu_config
        self.memory: Dict[int, int] = {}  # addr -> byte value
        self.erase_counts: Dict[int, int] = {s.number: 0 for s in mcu_config.sectors}
        self.total_erase_time = 0.0
        self.total_program_time = 0.0
        self.total_operations = 0
        self._initialize()

    def _initialize(self):
        """Initialize all Flash memory to 0xFF (erased state)."""
        for sector in self.mcu.sectors:
            for offset in range(sector.size):
                self.memory[sector.base_addr + offset] = 0xFF

    def get_sector(self, addr: int) -> Optional[FlashSector]:
        """Find which sector contains the given address."""
        for sector in self.mcu.sectors:
            if sector.base_addr <= addr < sector.base_addr + sector.size:
                return sector
        return None

    def get_sector_by_number(self, num: int) -> Optional[FlashSector]:
        """Find sector by its number."""
        for sector in self.mcu.sectors:
            if sector.number == num:
                return sector
        return None

    def read_byte(self, addr: int) -> int:
        """Read a single byte from Flash."""
        if addr < 0x0800_0000:
            raise FlashError(f"Address 0x{addr:08X} is below Flash base")
        return self.memory.get(addr, 0xFF)

    def read_word(self, addr: int, size: int = 4) -> int:
        """Read a multi-byte word (little-endian)."""
        value = 0
        for i in range(size):
            value |= self.read_byte(addr + i) << (8 * i)
        return value

    def read_bytes(self, addr: int, length: int) -> bytes:
        """Read a sequence of bytes."""
        return bytes(self.read_byte(addr + i) for i in range(length))

    def program_word(self, addr: int, value: int, size: int = 4) -> None:
        """
        Program a word into Flash.
        STM32 rule: can only change 1->0, never 0->1 without erase.
        """
        sector = self.get_sector(addr)
        if not sector:
            raise FlashWriteError(f"Address 0x{addr:08X} not in any Flash sector")

        # Check alignment
        if addr % size != 0:
            raise FlashWriteError(f"Address 0x{addr:08X} not aligned to {size} bytes")

        # Check if programming within sector bounds
        if addr + size > sector.base_addr + sector.size:
            raise FlashWriteError(f"Write exceeds sector bounds")

        # STM32 Flash programming rule: only clear bits
        for i in range(size):
            byte_addr = addr + i
            old_byte = self.memory.get(byte_addr, 0xFF)
            new_byte = (value >> (8 * i)) & 0xFF

            # Check: cannot set bits from 0 to 1
            if old_byte & ~new_byte:
                # This would be a programming error on real STM32
                # (trying to write 1 where there's already 0)
                # On some STM32 this triggers PGPERR
                pass  # We allow it in simulation but log it

            self.memory[byte_addr] = old_byte & new_byte

        self.total_program_time += self.mcu.program_time
        self.total_operations += 1

    def erase_sector(self, sector_num: int) -> None:
        """Erase an entire Flash sector (set all bytes to 0xFF)."""
        sector = self.get_sector_by_number(sector_num)
        if not sector:
            raise FlashEraseError(f"Invalid sector number: {sector_num}")

        for offset in range(sector.size):
            self.memory[sector.base_addr + offset] = 0xFF

        self.erase_counts[sector_num] += 1

        # Track erase time
        if sector.size <= 16 * 1024:
            self.total_erase_time += self.mcu.erase_time_16k
        elif sector.size <= 64 * 1024:
            self.total_erase_time += self.mcu.erase_time_64k
        elif sector.size <= 128 * 1024:
            self.total_erase_time += self.mcu.erase_time_128k
        else:
            self.total_erase_time += self.mcu.erase_time_256k

        self.total_operations += 1

    def dump_sector(self, sector_num: int, max_bytes: int = 256) -> str:
        """Create a hex dump of a sector."""
        sector = self.get_sector_by_number(sector_num)
        if not sector:
            return f"Sector {sector_num} not found"

        lines = []
        lines.append(f"=== {sector.name} (0x{sector.base_addr:08X}, {sector.size} bytes, "
                     f"erases: {self.erase_counts[sector_num]}) ===")

        for offset in range(0, min(max_bytes, sector.size), 16):
            addr = sector.base_addr + offset
            hex_bytes = " ".join(f"{self.read_byte(addr + i):02X}" for i in range(16))
            ascii_chars = "".join(
                chr(self.read_byte(addr + i)) if 32 <= self.read_byte(addr + i) < 127 else "."
                for i in range(16)
            )
            lines.append(f"0x{addr:08X}: {hex_bytes}  {ascii_chars}")

        return "\n".join(lines)

    def get_statistics(self) -> Dict:
        """Get Flash operation statistics."""
        return {
            "total_erase_time_sec": round(self.total_erase_time, 3),
            "total_program_time_sec": round(self.total_program_time, 6),
            "total_operations": self.total_operations,
            "erase_counts": {f"Sector_{k}": v for k, v in self.erase_counts.items()},
            "max_erase_count": max(self.erase_counts.values()) if self.erase_counts else 0,
            "min_erase_count": min(self.erase_counts.values()) if self.erase_counts else 0,
        }


# =============================================================================
# Wear-Leveling Driver Structures
# =============================================================================

class PageStatus(Enum):
    ERASED = 0xFFFF
    ACTIVE = 0xABCD
    FULL = 0x1234
    COPYING = 0xCDEF  # Added for atomic GC
    CORRUPTED = 0x0000


@dataclass
class PageHeader:
    """Flash page header structure (matches C struct)."""
    magic: int = 0xDEADBEEF
    erase_count: int = 0
    status: int = PageStatus.ERASED.value
    sequence: int = 0

    def to_bytes(self) -> bytes:
        return (
            self.magic.to_bytes(4, 'little') +
            self.erase_count.to_bytes(4, 'little') +
            self.status.to_bytes(2, 'little') +
            self.sequence.to_bytes(4, 'little') +
            b'\xFF\xFF'  # 2-byte padding for 4-byte alignment
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PageHeader':
        if len(data) < 14:
            return cls(magic=0, erase_count=0, status=PageStatus.CORRUPTED.value, sequence=0)
        return cls(
            magic=int.from_bytes(data[0:4], 'little'),
            erase_count=int.from_bytes(data[4:8], 'little'),
            status=int.from_bytes(data[8:10], 'little'),
            sequence=int.from_bytes(data[10:14], 'little'),
        )


@dataclass
class FlashRecord:
    """Flash record structure (32 bytes total)."""
    id: int = 0xFFFF
    len: int = 0xFFFF
    checksum: int = 0xFFFF
    data: bytes = field(default_factory=lambda: b'\xFF' * 24)

    def to_bytes(self) -> bytes:
        return (
            self.id.to_bytes(2, 'little') +
            self.len.to_bytes(2, 'little') +
            self.checksum.to_bytes(2, 'little') +
            self.data
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'FlashRecord':
        if len(data) < 32:
            return cls(id=0, len=0, checksum=0, data=b'\x00' * 24)
        return cls(
            id=int.from_bytes(data[0:2], 'little'),
            len=int.from_bytes(data[2:4], 'little'),
            checksum=int.from_bytes(data[4:6], 'little'),
            data=data[6:30],
        )

    def is_valid(self) -> bool:
        return self.id != 0xFFFF and self.len != 0xFFFF and self.len <= 24

    def is_deleted(self) -> bool:
        return self.len == 0x0000

    def compute_checksum(self) -> int:
        """Compute CRC-16-like checksum over id+len+data."""
        data_to_hash = self.id.to_bytes(2, 'little') + self.len.to_bytes(2, 'little') + self.data
        crc = 0xFFFF
        for byte in data_to_hash:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF


# =============================================================================
# Wear-Leveling Driver Simulation
# =============================================================================

class DriverMode(Enum):
    """Select which version of the driver to simulate."""
    BUGGY = "buggy"      # Original code with bugs C1-C7
    FIXED = "fixed"      # Corrected version


class WearLevelingDriver:
    """
    Simulates the wear-leveling driver behavior.
    Can operate in BUGGY mode (original) or FIXED mode (corrected).
    """

    HEADER_SIZE = 16  # 14 bytes header + 2 bytes padding for 4-byte alignment
    RECORD_SIZE = 32
    MAGIC = 0xDEADBEEF

    def __init__(self, flash: FlashMemory, page_addrs: List[int], mode: DriverMode = DriverMode.FIXED):
        self.flash = flash
        self.page_addrs = sorted(page_addrs)
        self.mode = mode
        self.page_count = len(page_addrs)
        self.page_size = self._get_page_size()

        # Runtime state
        self.active_page_idx = -1
        self.sequence_counter = 0
        self.next_record_offset = {}  # page_idx -> offset within page

        # Statistics
        self.write_count = 0
        self.read_count = 0
        self.delete_count = 0
        self.gc_count = 0
        self.power_cut_events = 0
        self.data_loss_events = 0
        self.corruption_events = 0

        # Power cut simulation
        self._power_cut_enabled = False
        self._power_cut_probability = 0.0
        self._power_cut_phase = None  # 'erase', 'program', 'gc', 'any'

        self._initialize()

    def _get_page_size(self) -> int:
        """Determine page size from first page address."""
        sector = self.flash.get_sector(self.page_addrs[0])
        return sector.size if sector else 16 * 1024

    def _power_cut_check(self, phase: str) -> bool:
        """Check if a power cut should occur during this phase."""
        if not self._power_cut_enabled:
            return False
        if self._power_cut_phase not in (phase, 'any'):
            return False
        if random.random() > self._power_cut_probability:
            return False

        self.power_cut_events += 1
        raise PowerCutException(f"Power cut during {phase}!")

    def _initialize(self):
        """Initialize pages - scan existing state or format."""
        for i, addr in enumerate(self.page_addrs):
            self.next_record_offset[i] = self.HEADER_SIZE

            # Read header
            header_data = self.flash.read_bytes(addr, self.HEADER_SIZE)
            header = PageHeader.from_bytes(header_data)

            if header.magic == self.MAGIC and header.status == PageStatus.ACTIVE.value:
                # Found an active page
                if self.mode == DriverMode.FIXED:
                    # FIXED: handle recovery - if multiple ACTIVE, keep highest sequence
                    if self.active_page_idx == -1 or header.sequence > self.sequence_counter:
                        self.active_page_idx = i
                        self.sequence_counter = header.sequence
                else:
                    # BUGGY: first active page wins (C6 bug)
                    if self.active_page_idx == -1:
                        self.active_page_idx = i
                        self.sequence_counter = header.sequence

        # If no active page found, format all
        if self.active_page_idx == -1:
            self._format_all()

    def _format_all(self):
        """Erase all pages and set first as active."""
        for i, addr in enumerate(self.page_addrs):
            sector = self.flash.get_sector(addr)
            if sector:
                self.flash.erase_sector(sector.number)
            self.next_record_offset[i] = self.HEADER_SIZE

        self.active_page_idx = 0
        self.sequence_counter = 1
        self._write_page_header(0, PageStatus.ACTIVE, 0)

    def _write_page_header(self, page_idx: int, status: PageStatus, erase_count: int):
        """Write page header to Flash."""
        addr = self.page_addrs[page_idx]
        header = PageHeader(
            magic=self.MAGIC,
            erase_count=erase_count,
            status=status.value,
            sequence=self.sequence_counter,
        )
        data = header.to_bytes()
        for i in range(0, len(data), 4):
            word = int.from_bytes(data[i:i+4], 'little')
            self.flash.program_word(addr + i, word, 4)

    def _read_page_header(self, page_idx: int) -> PageHeader:
        """Read page header from Flash."""
        addr = self.page_addrs[page_idx]
        data = self.flash.read_bytes(addr, self.HEADER_SIZE)
        return PageHeader.from_bytes(data)

    def _find_record(self, page_idx: int, record_id: int) -> Tuple[int, FlashRecord]:
        """Find a record by ID within a page. Returns (offset, record)."""
        addr = self.page_addrs[page_idx]
        offset = self.HEADER_SIZE

        found_offset = -1
        found_record = None

        while offset + self.RECORD_SIZE <= self.page_size:
            rec_data = self.flash.read_bytes(addr + offset, self.RECORD_SIZE)
            record = FlashRecord.from_bytes(rec_data)

            if record.id == record_id and record.is_valid() and not record.is_deleted():
                if self.mode == DriverMode.FIXED:
                    # FIXED: return LAST occurrence (most recent)
                    found_offset = offset
                    found_record = record
                else:
                    # BUGGY: return FIRST occurrence (C6 bug)
                    if found_offset == -1:
                        found_offset = offset
                        found_record = record

            offset += self.RECORD_SIZE

        return found_offset, found_record

    def _count_valid_records(self, page_idx: int) -> int:
        """Count valid (non-deleted) records in a page."""
        addr = self.page_addrs[page_idx]
        offset = self.HEADER_SIZE
        count = 0

        while offset + self.RECORD_SIZE <= self.page_size:
            rec_data = self.flash.read_bytes(addr + offset, self.RECORD_SIZE)
            record = FlashRecord.from_bytes(rec_data)
            if record.is_valid() and not record.is_deleted():
                count += 1
            offset += self.RECORD_SIZE

        return count

    def _get_all_records(self, page_idx: int) -> List[Tuple[int, FlashRecord]]:
        """Get all valid records from a page as list of (offset, record)."""
        addr = self.page_addrs[page_idx]
        offset = self.HEADER_SIZE
        records = []

        while offset + self.RECORD_SIZE <= self.page_size:
            rec_data = self.flash.read_bytes(addr + offset, self.RECORD_SIZE)
            record = FlashRecord.from_bytes(rec_data)
            if record.is_valid() and not record.is_deleted():
                records.append((offset, record))
            offset += self.RECORD_SIZE

        return records

    def write_record(self, record_id: int, data: bytes) -> bool:
        """Write a record to Flash."""
        self.write_count += 1

        if len(data) > 24:
            data = data[:24]

        # Pad data to 24 bytes
        data = data + b'\x00' * (24 - len(data))

        if self.mode == DriverMode.BUGGY:
            # BUGGY: delete old record BEFORE writing new one (C4 bug)
            self._delete_record_internal(record_id)

        # Check if page is full
        if self.next_record_offset[self.active_page_idx] + self.RECORD_SIZE > self.page_size:
            if not self._garbage_collect():
                return False

        # Write new record
        addr = self.page_addrs[self.active_page_idx] + self.next_record_offset[self.active_page_idx]

        record = FlashRecord(
            id=record_id,
            len=len(data.rstrip(b'\x00') or data),
            checksum=0,
            data=data
        )
        record.checksum = record.compute_checksum()

        rec_bytes = record.to_bytes()
        self._power_cut_check('program')

        for i in range(0, len(rec_bytes), 4):
            word = int.from_bytes(rec_bytes[i:i+4], 'little')
            self.flash.program_word(addr + i, word, 4)

        self.next_record_offset[self.active_page_idx] += self.RECORD_SIZE

        if self.mode == DriverMode.FIXED:
            # FIXED: delete old record AFTER writing new one
            self._delete_record_internal(record_id, skip_current=True)

        return True

    def read_record(self, record_id: int) -> Optional[bytes]:
        """Read a record by ID."""
        self.read_count += 1

        # Search active page first (FIXED behavior)
        if self.active_page_idx >= 0:
            offset, record = self._find_record(self.active_page_idx, record_id)
            if record:
                # Verify checksum
                expected = record.compute_checksum()
                if record.checksum == expected:
                    return record.data[:record.len] if record.len <= 24 else record.data
                else:
                    self.corruption_events += 1

        # Search other pages
        for i in range(self.page_count):
            if i == self.active_page_idx:
                continue
            offset, record = self._find_record(i, record_id)
            if record:
                expected = record.compute_checksum()
                if record.checksum == expected:
                    return record.data[:record.len] if record.len <= 24 else record.data
                else:
                    self.corruption_events += 1

        return None

    def delete_record(self, record_id: int) -> bool:
        """Delete a record by ID."""
        self.delete_count += 1
        return self._delete_record_internal(record_id)

    def _delete_record_internal(self, record_id: int, skip_current: bool = False) -> bool:
        """Internal delete implementation."""
        pages_to_search = list(range(self.page_count))
        if skip_current and self.active_page_idx >= 0:
            pages_to_search.remove(self.active_page_idx)

        for page_idx in pages_to_search:
            addr = self.page_addrs[page_idx]
            offset = self.HEADER_SIZE

            while offset + self.RECORD_SIZE <= self.page_size:
                rec_data = self.flash.read_bytes(addr + offset, self.RECORD_SIZE)
                record = FlashRecord.from_bytes(rec_data)

                if record.id == record_id and record.is_valid() and not record.is_deleted():
                    # Mark as deleted by setting len to 0
                    delete_addr = addr + offset + 2  # offset of 'len' field

                    if self.mode == DriverMode.BUGGY:
                        # BUGGY: unaligned write (C5 bug) - retour ignoré sur vrai hardware
                        # On simule l'échec silencieux (comme le vrai driver)
                        try:
                            self.flash.program_word(delete_addr, 0x0000FFFF, 4)
                        except FlashWriteError:
                            pass  # BUGGY: error silently ignored (C5)
                    else:
                        # FIXED: aligned 4-byte write covering len field
                        self.flash.program_word(delete_addr & ~0x3, 0x0000FFFF, 4)

                    return True

                offset += self.RECORD_SIZE

        return False

    def _garbage_collect(self) -> bool:
        """Perform garbage collection."""
        self.gc_count += 1

        src_page = self.active_page_idx
        if src_page < 0:
            return False

        # Find destination page (erased state)
        dst_page = -1
        for i in range(self.page_count):
            if i == src_page:
                continue
            header = self._read_page_header(i)
            if header.status == PageStatus.ERASED.value or header.magic != self.MAGIC:
                dst_page = i
                break

        if dst_page == -1:
            # No free page available
            return False

        # Get valid records from source
        records = self._get_all_records(src_page)

        if self.mode == DriverMode.FIXED:
            # FIXED: Atomic GC with COPYING state
            self.sequence_counter += 1

            # Mark destination as COPYING first
            self._power_cut_check('gc')
            self._write_page_header(dst_page, PageStatus.COPYING, 
                                    self._read_page_header(dst_page).erase_count)

            # Copy valid records
            offset = self.HEADER_SIZE
            for _, record in records:
                addr = self.page_addrs[dst_page] + offset
                rec_bytes = record.to_bytes()
                for i in range(0, len(rec_bytes), 4):
                    word = int.from_bytes(rec_bytes[i:i+4], 'little')
                    self.flash.program_word(addr + i, word, 4)
                offset += self.RECORD_SIZE

            self.next_record_offset[dst_page] = offset

            # Mark destination as ACTIVE
            self._power_cut_check('gc')
            self._write_page_header(dst_page, PageStatus.ACTIVE,
                                    self._read_page_header(dst_page).erase_count + 1)

            # Mark source as ERASED
            self._write_page_header(src_page, PageStatus.ERASED,
                                    self._read_page_header(src_page).erase_count)

            # Erase source sector
            self._power_cut_check('erase')
            sector = self.flash.get_sector(self.page_addrs[src_page])
            if sector:
                self.flash.erase_sector(sector.number)

            self.active_page_idx = dst_page

        else:
            # BUGGY: Non-atomic GC (C3 bug)
            self.sequence_counter += 1

            # Copy records first
            offset = self.HEADER_SIZE
            for _, record in records:
                addr = self.page_addrs[dst_page] + offset
                rec_bytes = record.to_bytes()
                for i in range(0, len(rec_bytes), 4):
                    word = int.from_bytes(rec_bytes[i:i+4], 'little')
                    self.flash.program_word(addr + i, word, 4)
                offset += self.RECORD_SIZE

            self.next_record_offset[dst_page] = offset

            # Mark source as ERASED BEFORE destination as ACTIVE (C3 bug)
            self._power_cut_check('gc')
            self._write_page_header(src_page, PageStatus.ERASED,
                                    self._read_page_header(src_page).erase_count)

            sector = self.flash.get_sector(self.page_addrs[src_page])
            if sector:
                self.flash.erase_sector(sector.number)

            # Then mark destination as ACTIVE
            self._write_page_header(dst_page, PageStatus.ACTIVE,
                                    self._read_page_header(src_page).erase_count + 1)  # C2 bug: wrong erase count

            self.active_page_idx = dst_page

        # C7 bug check: verify capacity after GC
        if self.mode == DriverMode.FIXED:
            if self.next_record_offset[self.active_page_idx] + self.RECORD_SIZE > self.page_size:
                return False  # Page full even after GC

        return True

    def enable_power_cut_simulation(self, probability: float, phase: str = 'any'):
        """Enable random power cut simulation."""
        self._power_cut_enabled = True
        self._power_cut_probability = probability
        self._power_cut_phase = phase

    def disable_power_cut_simulation(self):
        """Disable power cut simulation."""
        self._power_cut_enabled = False
        self._power_cut_probability = 0.0

    def get_page_status(self, page_idx: int) -> Dict:
        """Get detailed status of a page."""
        header = self._read_page_header(page_idx)
        valid_count = self._count_valid_records(page_idx)
        used_bytes = self.next_record_offset.get(page_idx, self.HEADER_SIZE)

        return {
            "index": page_idx,
            "address": f"0x{self.page_addrs[page_idx]:08X}",
            "magic": f"0x{header.magic:08X}",
            "status": header.status,
            "status_name": self._status_name(header.status),
            "erase_count": header.erase_count,
            "sequence": header.sequence,
            "valid_records": valid_count,
            "used_bytes": used_bytes,
            "free_bytes": self.page_size - used_bytes,
            "usage_percent": round((used_bytes / self.page_size) * 100, 1),
        }

    def _status_name(self, status_val: int) -> str:
        for status in PageStatus:
            if status.value == status_val:
                return status.name
        return f"UNKNOWN(0x{status_val:04X})"

    def get_all_records(self) -> Dict[int, bytes]:
        """Get all current records as dict {id: data}."""
        records = {}
        for page_idx in range(self.page_count):
            for offset, record in self._get_all_records(page_idx):
                if record.id not in records or self.mode == DriverMode.FIXED:
                    # FIXED: overwrite with newer (from higher page/offset)
                    records[record.id] = record.data[:record.len] if record.len <= 24 else record.data
        return records

    def get_statistics(self) -> Dict:
        """Get driver statistics."""
        return {
            "mode": self.mode.value,
            "page_count": self.page_count,
            "page_size": self.page_size,
            "writes": self.write_count,
            "reads": self.read_count,
            "deletes": self.delete_count,
            "gc_cycles": self.gc_count,
            "power_cuts": self.power_cut_events,
            "data_loss": self.data_loss_events,
            "corruptions": self.corruption_events,
            "active_page": self.active_page_idx,
            "sequence": self.sequence_counter,
            "records_stored": len(self.get_all_records()),
        }

    def print_state(self):
        """Print complete state of the driver."""
        print("\n" + "=" * 70)
        print(f"WEAR-LEVELING STATE  [Mode: {self.mode.value.upper()}]")
        print("=" * 70)

        for i in range(self.page_count):
            status = self.get_page_status(i)
            marker = " <<< ACTIVE" if i == self.active_page_idx else ""
            print(f"\nPage {i} @ {status['address']}{marker}")
            print(f"  Status: {status['status_name']} | Erase count: {status['erase_count']} | "
                  f"Sequence: {status['sequence']}")
            print(f"  Records: {status['valid_records']} valid | "
                  f"Used: {status['used_bytes']}/{self.page_size} bytes ({status['usage_percent']}%)")

            # Show records
            for offset, record in self._get_all_records(i):
                data_preview = record.data[:min(record.len, 24)]
                try:
                    text = data_preview.decode('utf-8', errors='replace').replace('\n', ' ')
                except:
                    text = data_preview.hex()
                print(f"    [ID={record.id:3d}, len={record.len:2d}] {text[:30]}")

        print("\n" + "-" * 70)
        stats = self.get_statistics()
        print(f"Writes: {stats['writes']} | Reads: {stats['reads']} | Deletes: {stats['deletes']} | "
              f"GC: {stats['gc_cycles']}")
        print(f"Power cuts: {stats['power_cuts']} | Data loss events: {stats['data_loss']} | "
              f"Corruptions: {stats['corruptions']}")
        print("=" * 70 + "\n")


class PowerCutException(Exception):
    """Raised when a simulated power cut occurs."""
    pass


# =============================================================================
# Test Scenarios
# =============================================================================

class TestScenario:
    """Base class for test scenarios."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.results = []

    def run(self, mcu_name: str, mode: DriverMode, **kwargs) -> Dict:
        raise NotImplementedError

    def _create_driver(self, mcu_name: str, mode: DriverMode, page_indices: List[int]) -> Tuple[FlashMemory, WearLevelingDriver]:
        """Create a Flash memory and driver instance."""
        mcu = MCU_DATABASE[mcu_name]
        flash = FlashMemory(mcu)
        page_addrs = [mcu.sectors[i].base_addr for i in page_indices]
        driver = WearLevelingDriver(flash, page_addrs, mode)
        return flash, driver


class BasicWriteReadTest(TestScenario):
    """Test basic write and read operations."""

    def __init__(self):
        super().__init__("basic_write_read", "Basic write/read/delete operations")

    def run(self, mcu_name: str, mode: DriverMode, **kwargs) -> Dict:
        flash, driver = self._create_driver(mcu_name, mode, [1, 2])  # Use sectors 1,2 (16KB each on F4)

        # Write some records
        test_data = {
            1: b"Hello, World!",
            2: b"STM32 Flash WL",
            3: b"Test record 3",
        }

        for rec_id, data in test_data.items():
            driver.write_record(rec_id, data)

        # Read back and verify
        results = {"writes_ok": 0, "reads_ok": 0, "mismatches": 0}

        for rec_id, expected in test_data.items():
            read_data = driver.read_record(rec_id)
            if read_data == expected:
                results["reads_ok"] += 1
            else:
                results["mismatches"] += 1
                print(f"  MISMATCH: ID={rec_id}, expected={expected}, got={read_data}")

        results["writes_ok"] = len(test_data)
        results["stats"] = driver.get_statistics()
        results["flash_stats"] = flash.get_statistics()

        return results


class StressTest(TestScenario):
    """Stress test with many writes and GC cycles."""

    def __init__(self):
        super().__init__("stress", "Stress test with many writes and GC cycles")

    def run(self, mcu_name: str, mode: DriverMode, num_writes: int = 500, **kwargs) -> Dict:
        flash, driver = self._create_driver(mcu_name, mode, [1, 2])

        errors = []
        written_data = {}  # Track what we expect to find

        for i in range(num_writes):
            rec_id = (i % 50) + 1  # Cycle through 50 different IDs
            data = f"Record_{rec_id}_v{i}".encode()[:24]

            try:
                driver.write_record(rec_id, data)
                written_data[rec_id] = data
            except Exception as e:
                errors.append(f"Write {i} failed: {e}")

        # Verify all expected records
        verified = 0
        lost = 0
        corrupted = 0

        for rec_id, expected in written_data.items():
            read_data = driver.read_record(rec_id)
            if read_data is None:
                lost += 1
            elif read_data != expected:
                corrupted += 1
            else:
                verified += 1

        return {
            "total_writes": num_writes,
            "errors": len(errors),
            "verified": verified,
            "lost": lost,
            "corrupted": corrupted,
            "stats": driver.get_statistics(),
            "flash_stats": flash.get_statistics(),
        }


class PowerCutTest(TestScenario):
    """Test resilience to power cuts during operations."""

    def __init__(self):
        super().__init__("power_cut", "Power cut resilience test with fault injection")

    def run(self, mcu_name: str, mode: DriverMode, num_iterations: int = 100, 
            cut_probability: float = 0.05, phase: str = 'any', **kwargs) -> Dict:

        mcu = MCU_DATABASE[mcu_name]
        results = {
            "iterations": num_iterations,
            "power_cuts": 0,
            "successful_recovery": 0,
            "data_loss": 0,
            "corruption": 0,
        }

        for iteration in range(num_iterations):
            # Fresh start for each iteration
            flash = FlashMemory(mcu)
            page_addrs = [mcu.sectors[1].base_addr, mcu.sectors[2].base_addr]
            driver = WearLevelingDriver(flash, page_addrs, mode)

            # Write some baseline data
            baseline = {i: f"baseline_{i}".encode() for i in range(1, 6)}
            for rec_id, data in baseline.items():
                driver.write_record(rec_id, data)

            # Enable power cut simulation
            driver.enable_power_cut_simulation(cut_probability, phase)

            # Try more operations
            try:
                for i in range(20):
                    rec_id = (i % 5) + 1
                    data = f"update_{iteration}_{i}".encode()[:24]
                    driver.write_record(rec_id, data)
            except PowerCutException:
                results["power_cuts"] += 1

                # Simulate reboot: create new driver with same flash
                try:
                    recovered_driver = WearLevelingDriver(flash, page_addrs, mode)
                    results["successful_recovery"] += 1

                    # Check if baseline data is still there
                    for rec_id, expected in baseline.items():
                        read_data = recovered_driver.read_record(rec_id)
                        if read_data is None:
                            results["data_loss"] += 1
                        elif read_data != expected and not read_data.startswith(b"update_"):
                            results["corruption"] += 1

                except Exception as e:
                    results["data_loss"] += 1

        return results


class SectorMappingTest(TestScenario):
    """Test correct sector mapping for different MCUs."""

    def __init__(self):
        super().__init__("sector_mapping", "Verify sector sizes and addresses match MCU datasheet")

    def run(self, mcu_name: str, mode: DriverMode, **kwargs) -> Dict:
        mcu = MCU_DATABASE[mcu_name]

        results = {
            "mcu": mcu.name,
            "flash_size": mcu.flash_size,
            "sector_count": len(mcu.sectors),
            "sectors": [],
            "total_size_check": 0,
        }

        for sector in mcu.sectors:
            results["sectors"].append({
                "number": sector.number,
                "name": sector.name,
                "base": f"0x{sector.base_addr:08X}",
                "size_kb": sector.size // 1024,
            })
            results["total_size_check"] += sector.size

        results["size_match"] = (results["total_size_check"] == mcu.flash_size)

        return results


class ComparisonTest(TestScenario):
    """Compare BUGGY vs FIXED mode on the same scenario."""

    def __init__(self):
        super().__init__("comparison", "Compare buggy vs fixed driver behavior")

    def run(self, mcu_name: str, mode: DriverMode = None, scenario_name: str = "stress", **kwargs) -> Dict:
        scenario_map = {
            "stress": StressTest(),
            "power_cut": PowerCutTest(),
            "basic": BasicWriteReadTest(),
        }

        scenario = scenario_map.get(scenario_name, StressTest())

        # Run with BUGGY mode
        print("Running BUGGY mode...")
        buggy_results = scenario.run(mcu_name, DriverMode.BUGGY, **kwargs)

        # Run with FIXED mode
        print("Running FIXED mode...")
        fixed_results = scenario.run(mcu_name, DriverMode.FIXED, **kwargs)

        return {
            "scenario": scenario_name,
            "buggy": buggy_results,
            "fixed": fixed_results,
            "improvement": {
                "data_loss_reduction": buggy_results.get("lost", 0) - fixed_results.get("lost", 0),
                "corruption_reduction": buggy_results.get("corrupted", 0) - fixed_results.get("corrupted", 0),
            }
        }



# =============================================================================
# HTML Visualizer Generator (embedded for --viz option)
# =============================================================================

HTML_VIZ_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STM32 Flash WL — {{MCU_NAME}} — {{MODE}}</title>
<style>
  :root {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --border: #30363d; --text: #c9d1d9; --text2: #8b949e; --text3: #484f58;
    --accent: #58a6ff; --ok: #3fb950; --warn: #d29922; --err: #f85149;
    --chart1: #58a6ff; --font: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    --mono: "SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg:#ffffff; --bg2:#f6f8fa; --bg3:#eaeef2; --border:#d0d7de; --text:#24292f; --text2:#57606a; --text3:#8c959f; }
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:var(--font); background:var(--bg); color:var(--text); font-size:14px; }
  .container { max-width:900px; margin:0 auto; padding:24px; }
  h1 { font-size:20px; font-weight:600; margin:0 0 4px; }
  .subtitle { color:var(--text2); font-size:12px; margin-bottom:20px; }
  .toolbar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; align-items:center; }
  .toolbar select, .toolbar button, .toolbar input {
    padding:6px 12px; border-radius:6px; border:1px solid var(--border);
    background:var(--bg2); color:var(--text); font:inherit; font-size:13px; cursor:pointer;
  }
  .toolbar button:hover { background:var(--bg3); }
  .toolbar button.primary { background:var(--text); color:var(--bg); border-color:var(--text); }
  .toolbar button.danger { border-color:var(--err); color:var(--err); }
  .toolbar button.danger:hover { background:rgba(248,81,73,0.08); }
  .badge { padding:2px 10px; border-radius:6px; font-size:12px; font-weight:500; border:1px solid var(--border); }
  .badge.buggy { background:rgba(248,81,73,0.1); color:var(--err); border-color:var(--err); }
  .badge.fixed { background:rgba(63,185,80,0.1); color:var(--ok); border-color:var(--ok); }
  .sector-map { margin-bottom:20px; }
  .sector-title { font-size:12px; font-weight:600; color:var(--text2); margin-bottom:8px; }
  .sector-row { display:flex; align-items:center; gap:8px; margin-bottom:3px; font-size:11px; }
  .sector-name { width:80px; text-align:right; color:var(--text2); flex-shrink:0; }
  .sector-bar-wrap { flex:1; height:16px; background:var(--bg3); border-radius:3px; overflow:hidden; position:relative; }
  .sector-bar { height:100%; border-radius:3px; }
  .sector-bar.wl { background:var(--chart1); }
  .sector-bar.code { background:var(--text3); }
  .sector-size { width:50px; text-align:right; color:var(--text2); flex-shrink:0; }
  .pages-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:20px; }
  @media(max-width:640px){ .pages-grid { grid-template-columns:1fr; } }
  .page-card { border:1px solid var(--border); border-radius:10px; padding:14px; background:var(--bg2); transition:border-color 0.15s; }
  .page-card.active { border-color:var(--text); }
  .page-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .page-title { font-size:14px; font-weight:600; }
  .page-status { font-size:11px; padding:2px 8px; border-radius:5px; font-weight:500; }
  .page-status.ERASED { background:rgba(139,148,158,0.12); color:var(--text2); }
  .page-status.ACTIVE { background:rgba(63,185,80,0.12); color:var(--ok); }
  .page-status.COPYING { background:rgba(88,166,255,0.12); color:var(--accent); }
  .page-status.FULL { background:rgba(210,153,34,0.12); color:var(--warn); }
  .page-meta { font-size:11px; color:var(--text2); margin-bottom:10px; }
  .records-grid { display:flex; flex-wrap:wrap; gap:3px; }
  .rec-cell { width:24px; height:24px; border-radius:4px; display:flex; align-items:center; justify-content:center; font-size:9px; font-weight:600; cursor:default; border:1px solid var(--border); position:relative; }
  .rec-cell.valid { background:var(--text); color:var(--bg); border-color:var(--text); }
  .rec-cell.deleted { background:rgba(248,81,73,0.12); color:var(--err); border-color:var(--err); }
  .rec-cell.empty { background:transparent; color:var(--text3); }
  .rec-cell:hover::after { content:attr(data-tip); position:absolute; bottom:28px; left:50%; transform:translateX(-50%); background:var(--text); color:var(--bg); padding:4px 10px; border-radius:6px; font-size:11px; white-space:nowrap; z-index:10; pointer-events:none; font-family:var(--font); }
  .stats-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:20px; }
  @media(max-width:640px){ .stats-grid { grid-template-columns:repeat(2,1fr); } }
  .stat-box { border:1px solid var(--border); border-radius:10px; padding:14px; text-align:center; background:var(--bg2); }
  .stat-value { font-size:26px; font-weight:600; font-variant-numeric:tabular-nums; }
  .stat-label { font-size:11px; color:var(--text2); margin-top:4px; }
  .log-panel { border:1px solid var(--border); border-radius:10px; padding:12px 14px; max-height:180px; overflow-y:auto; font-size:12px; font-family:var(--mono); line-height:1.6; background:var(--bg2); }
  .log-line .ts { color:var(--text3); margin-right:8px; }
  .log-line .ok { color:var(--ok); }
  .log-line .err { color:var(--err); }
  .log-line .warn { color:var(--warn); }
  .log-line .info { color:var(--accent); }
  .write-box { display:flex; gap:8px; margin-bottom:16px; }
  .write-box input { flex:1; padding:8px 12px; border-radius:8px; border:1px solid var(--border); background:var(--bg2); color:var(--text); font:inherit; }
  .write-box input::placeholder { color:var(--text3); }
</style>
</head>
<body>
<div class="container">
  <h1>STM32 Flash Wear-Leveling Visualizer</h1>
  <div class="subtitle">{{MCU_NAME}} — {{MODE}} mode — generated {{TIMESTAMP}}</div>
  <div class="toolbar">
    <span class="badge {{MODE_CLASS}}">{{MODE}}</span>
    <button onclick="app.reset()">Reset flash</button>
    <button class="danger" onclick="app.powerCut()">⚡ Power cut</button>
    <button onclick="app.gc()">Run GC</button>
    <button onclick="app.exportState()">Export JSON</button>
  </div>
  <div class="sector-map" id="sector-map"></div>
  <div class="write-box">
    <input id="write-input" type="text" placeholder="Type data to write (max 24 bytes)" maxlength="24" />
    <button class="primary" onclick="app.writeRecord()">Write record</button>
  </div>
  <div class="pages-grid" id="pages"></div>
  <div class="stats-grid" id="stats"></div>
  <div class="log-panel" id="log"></div>
</div>
<script>
(function(){
  const MCU_CFG = {{MCU_JSON}};
  const HEADER_SIZE = 16, RECORD_SIZE = 32, MAGIC = 0xDEADBEEF, IS_BUGGY = {{IS_BUGGY}};
  class FlashMem {
    constructor(cfg) { this.cfg = cfg; this.mem = new Map(); this.eraseCounts = {}; cfg.sectors.forEach(s => this.eraseCounts[s.n] = 0); this._init(); }
    _init() { this.cfg.sectors.forEach(s => { for (let i = 0; i < s.size; i++) this.mem.set(s.addr + i, 0xFF); }); }
    sectorOf(addr) { return this.cfg.sectors.find(s => s.addr <= addr && addr < s.addr + s.size); }
    read(addr, len) { const b = []; for (let i = 0; i < len; i++) b.push(this.mem.get(addr + i) ?? 0xFF); return b; }
    programWord(addr, val, size = 4) { const sec = this.sectorOf(addr); if (!sec) throw new Error("Out of flash"); if (addr % size !== 0) throw new Error("Unaligned"); for (let i = 0; i < size; i++) { const a = addr + i, old = this.mem.get(a) ?? 0xFF, nv = (val >> (8 * i)) & 0xFF; this.mem.set(a, old & nv); } }
    eraseSector(n) { const sec = this.cfg.sectors.find(s => s.n === n); if (!sec) throw new Error("Bad sector"); for (let i = 0; i < sec.size; i++) this.mem.set(sec.addr + i, 0xFF); this.eraseCounts[n]++; }
  }
  class WLDriver {
    constructor(flash, pageAddrs, buggy) {
      this.flash = flash; this.pageAddrs = [...pageAddrs]; this.buggy = buggy; this.pageCount = pageAddrs.length;
      this.pageSize = flash.cfg.pageSize; this.activeIdx = -1; this.seq = 0; this.nextOff = {};
      this.stats = { writes: 0, reads: 0, deletes: 0, gc: 0, powerCuts: 0, dataLoss: 0, corrupt: 0 };
      this._init();
    }
    _init() { for (let i = 0; i < this.pageCount; i++) { this.nextOff[i] = HEADER_SIZE; const h = this._readHeader(i); if (h.magic === MAGIC && h.status === 0xABCD) { if (this.buggy) { if (this.activeIdx < 0) { this.activeIdx = i; this.seq = h.seq; } } else { if (this.activeIdx < 0 || h.seq > this.seq) { this.activeIdx = i; this.seq = h.seq; } } } } if (this.activeIdx < 0) this._formatAll(); }
    _readHeader(pi) { const b = this.flash.read(this.pageAddrs[pi], 16); return { magic: (b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24), erase: (b[4] | b[5] << 8 | b[6] << 16 | b[7] << 24), status: (b[8] | b[9] << 8), seq: (b[10] | b[11] << 8 | b[12] << 16 | b[13] << 24) }; }
    _writeHeader(pi, status, eraseCount) { const addr = this.pageAddrs[pi]; const words = [MAGIC, eraseCount, (status & 0xFFFF) | ((this.seq & 0xFFFF) << 16), (this.seq >>> 16) | 0xFFFF0000]; words.forEach((w, i) => this.flash.programWord(addr + i * 4, w, 4)); }
    _formatAll() { this.pageAddrs.forEach((a, i) => { const s = this.flash.sectorOf(a); if (s) this.flash.eraseSector(s.n); this.nextOff[i] = HEADER_SIZE; }); this.activeIdx = 0; this.seq = 1; this._writeHeader(0, 0xABCD, 0); }
    _recordsOf(pi) { const addr = this.pageAddrs[pi], recs = []; for (let off = HEADER_SIZE; off + RECORD_SIZE <= this.pageSize; off += RECORD_SIZE) { const b = this.flash.read(addr + off, RECORD_SIZE); const id = b[0] | b[1] << 8, len = b[2] | b[3] << 8, cs = b[4] | b[5] << 8; const data = b.slice(6, 30); if (id !== 0xFFFF && len !== 0xFFFF && len <= 24) { recs.push({ off, id, len, cs, data, deleted: len === 0 }); } } return recs; }
    _findRec(pi, rid) { const recs = this._recordsOf(pi).filter(r => r.id === rid && !r.deleted); if (!recs.length) return null; return this.buggy ? recs[0] : recs[recs.length - 1]; }
    writeRecord(id, dataBytes) { this.stats.writes++; const db = dataBytes.slice(0, 24); const padded = [...db, ...Array(24 - db.length).fill(0)]; if (this.buggy) this._delInternal(id); if (this.nextOff[this.activeIdx] + RECORD_SIZE > this.pageSize) { if (!this._gc()) { app.log("GC failed — page full", "err"); return false; } } const addr = this.pageAddrs[this.activeIdx] + this.nextOff[this.activeIdx]; const rec = [id & 0xFF, (id >> 8) & 0xFF, db.length & 0xFF, (db.length >> 8) & 0xFF, 0, 0, ...padded]; for (let i = 0; i < 32; i += 4) { const w = rec[i] | rec[i + 1] << 8 | rec[i + 2] << 16 | rec[i + 3] << 24; this.flash.programWord(addr + i, w, 4); } this.nextOff[this.activeIdx] += RECORD_SIZE; if (!this.buggy) this._delInternal(id, true); return true; }
    readRecord(id) { this.stats.reads++; if (this.activeIdx >= 0) { const r = this._findRec(this.activeIdx, id); if (r) return r.data.slice(0, r.len); } for (let i = 0; i < this.pageCount; i++) { if (i === this.activeIdx) continue; const r = this._findRec(i, id); if (r) return r.data.slice(0, r.len); } return null; }
    _delInternal(id, skipActive = false) { for (let i = 0; i < this.pageCount; i++) { if (skipActive && i === this.activeIdx) continue; const addr = this.pageAddrs[i]; for (let off = HEADER_SIZE; off + RECORD_SIZE <= this.pageSize; off += RECORD_SIZE) { const b = this.flash.read(addr + off, RECORD_SIZE); const rid = b[0] | b[1] << 8, len = b[2] | b[3] << 8; if (rid === id && len !== 0xFFFF && len !== 0) { const delAddr = addr + off + 2; if (this.buggy) { try { this.flash.programWord(delAddr, 0x0000FFFF, 4); } catch (e) { } } else { this.flash.programWord(delAddr & ~0x3, 0x0000FFFF, 4); } return true; } } } return false; }
    deleteRecord(id) { this.stats.deletes++; return this._delInternal(id); }
    _gc() { this.stats.gc++; const src = this.activeIdx; let dst = -1; for (let i = 0; i < this.pageCount; i++) { if (i === src) continue; const h = this._readHeader(i); if (h.magic !== MAGIC || h.status === 0xFFFF) { dst = i; break; } } if (dst < 0) return false; const recs = this._recordsOf(src).filter(r => !r.deleted); this.seq++; if (this.buggy) { let off = HEADER_SIZE; recs.forEach(r => { const a = this.pageAddrs[dst] + off; const b = [r.id & 0xFF, (r.id >> 8) & 0xFF, r.len & 0xFF, (r.len >> 8) & 0xFF, r.cs & 0xFF, (r.cs >> 8) & 0xFF, ...r.data]; for (let i = 0; i < 32; i += 4) this.flash.programWord(a + i, b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24, 4); off += RECORD_SIZE; }); this.nextOff[dst] = off; this._writeHeader(src, 0xFFFF, this._readHeader(src).erase); const ss = this.flash.sectorOf(this.pageAddrs[src]); if (ss) this.flash.eraseSector(ss.n); this._writeHeader(dst, 0xABCD, this._readHeader(src).erase + 1); this.activeIdx = dst; } else { this._writeHeader(dst, 0xCDEF, this._readHeader(dst).erase); let off = HEADER_SIZE; recs.forEach(r => { const a = this.pageAddrs[dst] + off; const b = [r.id & 0xFF, (r.id >> 8) & 0xFF, r.len & 0xFF, (r.len >> 8) & 0xFF, r.cs & 0xFF, (r.cs >> 8) & 0xFF, ...r.data]; for (let i = 0; i < 32; i += 4) this.flash.programWord(a + i, b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24, 4); off += RECORD_SIZE; }); this.nextOff[dst] = off; this._writeHeader(dst, 0xABCD, this._readHeader(dst).erase + 1); this._writeHeader(src, 0xFFFF, this._readHeader(src).erase); const ss = this.flash.sectorOf(this.pageAddrs[src]); if (ss) this.flash.eraseSector(ss.n); this.activeIdx = dst; if (this.nextOff[dst] + RECORD_SIZE > this.pageSize) return false; } return true; }
  }
  const app = {
    mcuKey: "{{MCU_KEY}}", buggy: IS_BUGGY, flash: null, driver: null, recId: 1,
    init() { this.reset(); document.getElementById("write-input").addEventListener("keydown", e => { if (e.key === "Enter") this.writeRecord(); }); },
    reset() { const cfg = MCU_CFG; this.flash = new FlashMem(cfg); const addrs = cfg.wlSectors.map(si => cfg.sectors[si].addr); this.driver = new WLDriver(this.flash, addrs, this.buggy); this.recId = 1; this.render(); this.log(`Reset: ${cfg.name}, ${cfg.wlSectors.length} pages x ${cfg.pageSize / 1024}KB`); },
    writeRecord() { const inp = document.getElementById("write-input"); const text = inp.value.trim() || `rec_${this.recId}`; const bytes = text.split("").map(c => c.charCodeAt(0) & 0xFF); const ok = this.driver.writeRecord(this.recId, bytes); if (ok) { this.log(`Write ID=${this.recId} "${text}" -> OK`); this.recId++; inp.value = ""; } else { this.log(`Write ID=${this.recId} FAILED`, "err"); } this.render(); },
    gc() { const ok = this.driver._gc(); this.log(`GC -> ${ok ? "OK" : "FAILED"}`, ok ? "ok" : "err"); this.render(); },
    powerCut() { this.driver.stats.powerCuts++; const cfg = MCU_CFG; const addrs = cfg.wlSectors.map(si => cfg.sectors[si].addr); this.driver = new WLDriver(this.flash, addrs, this.buggy); this.log("Power cut simulated -- rebooted", "warn"); this.render(); },
    exportState() { const state = { mcu: this.mcuKey, mode: this.buggy ? "buggy" : "fixed", stats: this.driver.stats, pages: [] }; for (let i = 0; i < this.driver.pageCount; i++) { const h = this.driver._readHeader(i); const sec = this.flash.sectorOf(this.driver.pageAddrs[i]); state.pages.push({ index: i, address: `0x${this.driver.pageAddrs[i].toString(16).toUpperCase().padStart(8, "0")}`, status: h.status === 0xABCD ? "ACTIVE" : h.status === 0xCDEF ? "COPYING" : h.status === 0xFFFF ? "ERASED" : "UNKNOWN", eraseCount: this.flash.eraseCounts[sec ? sec.n : 0], sequence: h.seq, records: this.driver._recordsOf(i).map(r => ({ id: r.id, len: r.len, deleted: r.deleted, data: String.fromCharCode(...r.data.slice(0, r.len)).replace(/[^\x20-\x7E]/g, ".") })) }); } const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `wl_state_${this.mcuKey}_${Date.now()}.json`; a.click(); URL.revokeObjectURL(url); this.log("State exported to JSON", "ok"); },
    log(msg, cls = "info") { const el = document.getElementById("log"); const ts = new Date().toLocaleTimeString("en-GB", { hour12: false }); const line = document.createElement("div"); line.className = "log-line"; line.innerHTML = `<span class="ts">${ts}</span><span class="${cls}">${msg}</span>`; el.appendChild(line); el.scrollTop = el.scrollHeight; while (el.children.length > 60) el.removeChild(el.firstChild); },
    render() { this.renderSectors(); this.renderPages(); this.renderStats(); },
    renderSectors() { const cfg = MCU_CFG; const wlSet = new Set(cfg.wlSectors); const maxSize = Math.max(...cfg.sectors.map(s => s.size)); const container = document.getElementById("sector-map"); container.innerHTML = '<div class="sector-title">Flash sector map</div>'; cfg.sectors.forEach((s, idx) => { const isWl = wlSet.has(idx); const row = document.createElement("div"); row.className = "sector-row"; row.innerHTML = `<div class="sector-name">${s.name}</div><div class="sector-bar-wrap"><div class="sector-bar ${isWl ? "wl" : "code"}" style="width:${(s.size / maxSize * 100).toFixed(1)}%"></div></div><div class="sector-size">${s.size / 1024}KB</div>`; container.appendChild(row); }); },
    renderPages() { const container = document.getElementById("pages"); container.innerHTML = ""; for (let i = 0; i < this.driver.pageCount; i++) { const h = this.driver._readHeader(i); const recs = this.driver._recordsOf(i); const valid = recs.filter(r => !r.deleted); const totalSlots = Math.floor((this.driver.pageSize - HEADER_SIZE) / RECORD_SIZE); const isActive = i === this.driver.activeIdx; let statusName = "ERASED"; if (h.status === 0xABCD) statusName = "ACTIVE"; else if (h.status === 0xCDEF) statusName = "COPYING"; else if (h.magic === MAGIC && h.status !== 0xFFFF) statusName = "FULL"; const sec = this.flash.sectorOf(this.driver.pageAddrs[i]); const eraseCnt = this.flash.eraseCounts[sec ? sec.n : 0]; const card = document.createElement("div"); card.className = "page-card" + (isActive ? " active" : ""); card.innerHTML = `<div class="page-header"><div class="page-title">Page ${i} @ 0x${this.driver.pageAddrs[i].toString(16).toUpperCase().padStart(8, "0")}</div><div class="page-status ${statusName}">${statusName}</div></div><div class="page-meta">Erase count: ${eraseCnt} | Records: ${valid.length}/${totalSlots} | Seq: ${h.seq}</div><div class="records-grid" id="recs-${i}"></div>`; container.appendChild(card); const recContainer = card.querySelector(`#recs-${i}`); for (let slot = 0; slot < totalSlots; slot++) { const rec = recs[slot]; const el = document.createElement("div"); el.className = "rec-cell " + (rec ? (rec.deleted ? "deleted" : "valid") : "empty"); if (rec && !rec.deleted) { const txt = String.fromCharCode(...rec.data.slice(0, rec.len)).replace(/[^\x20-\x7E]/g, "."); el.textContent = rec.id; el.setAttribute("data-tip", `ID:${rec.id} len:${rec.len} "${txt}"`); } else if (rec && rec.deleted) { el.textContent = "x"; el.setAttribute("data-tip", `ID:${rec.id} DELETED`); } else { el.textContent = "."; el.setAttribute("data-tip", "empty"); } recContainer.appendChild(el); } } },
    renderStats() { const s = this.driver.stats; const grid = document.getElementById("stats"); const items = [{ v: s.writes, l: "Writes" }, { v: s.gc, l: "GC cycles" }, { v: s.powerCuts, l: "Power cuts", color: s.powerCuts ? "color:var(--warn)" : "" }, { v: s.reads, l: "Reads" }]; grid.innerHTML = items.map(it => `<div class="stat-box"><div class="stat-value" style="${it.color || ""}">${it.v}</div><div class="stat-label">${it.l}</div></div>`).join(""); }
  };
  app.init(); window.app = app;
})();
</script>
</body>
</html>
"""


def generate_viz_html(mcu_key: str, mode: str, output_path: str) -> str:
    """Generate a standalone HTML visualizer file."""
    from datetime import datetime
    mcu_cfg = MCU_DATABASE[mcu_key]
    mcu = mcu_cfg  # MCUConfig object
    wl_indices = mcu_cfg.wlSectors if hasattr(mcu_cfg, 'wlSectors') else [1, 2]
    # Calculate page size from wear-leveling sectors (they must be same size)
    wl_sectors = [mcu.sectors[i] for i in wl_indices]
    page_size = wl_sectors[0].size if wl_sectors else 16 * 1024
    # Convert MCU config to plain dict for JSON serialization
    mcu_dict = {
        "name": mcu.name,
        "flash_size": mcu.flash_size,
        "pageSize": page_size,
        "sectors": [{"n": s.number, "name": s.name, "addr": s.base_addr, "size": s.size} for s in mcu.sectors],
        "wlSectors": wl_indices,
    }
    mcu_json = json.dumps(mcu_dict)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = HTML_VIZ_TEMPLATE
    html = html.replace("{{MCU_NAME}}", mcu_dict["name"])
    html = html.replace("{{MCU_KEY}}", mcu_key)
    html = html.replace("{{MODE}}", mode.upper())
    html = html.replace("{{MODE_CLASS}}", mode)
    html = html.replace("{{MCU_JSON}}", mcu_json)
    html = html.replace("{{IS_BUGGY}}", "true" if mode == "buggy" else "false")
    html = html.replace("{{TIMESTAMP}}", timestamp)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# =============================================================================
# CLI Interface
# =============================================================================

SCENARIOS = {
    "basic": BasicWriteReadTest(),
    "stress": StressTest(),
    "power_cut": PowerCutTest(),
    "sector_mapping": SectorMappingTest(),
    "comparison": ComparisonTest(),
}


def main():
    parser = argparse.ArgumentParser(
        description="STM32 Flash Wear-Leveling Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic test on STM32F401 with fixed driver
  python stm32_wl_simulator.py --mcu STM32F401 --scenario basic --mode fixed

  # Stress test with 1000 writes
  python stm32_wl_simulator.py --mcu STM32F401 --scenario stress --writes 1000

  # Power cut resilience test
  python stm32_wl_simulator.py --mcu STM32F401 --scenario power_cut --faults 200 --prob 0.1

  # Compare buggy vs fixed
  python stm32_wl_simulator.py --mcu STM32F401 --scenario comparison --comp-scenario stress

  # Test STM32F767 dual-bank
  python stm32_wl_simulator.py --mcu STM32F767_DUAL --scenario stress --writes 500

  # List supported MCUs
  python stm32_wl_simulator.py --list-mcus
        """
    )

    parser.add_argument("--mcu", type=str, default="STM32F401",
                        choices=list(MCU_DATABASE.keys()),
                        help="Target MCU (default: STM32F401)")
    parser.add_argument("--scenario", type=str, default="basic",
                        choices=list(SCENARIOS.keys()),
                        help="Test scenario to run (default: basic)")
    parser.add_argument("--mode", type=str, default="fixed",
                        choices=["buggy", "fixed"],
                        help="Driver mode: buggy (original) or fixed (corrected)")
    parser.add_argument("--writes", type=int, default=500,
                        help="Number of writes for stress test (default: 500)")
    parser.add_argument("--faults", type=int, default=100,
                        help="Number of iterations for power cut test (default: 100)")
    parser.add_argument("--prob", type=float, default=0.05,
                        help="Power cut probability per operation (default: 0.05)")
    parser.add_argument("--phase", type=str, default="any",
                        choices=["any", "erase", "program", "gc"],
                        help="Phase where power cuts can occur (default: any)")
    parser.add_argument("--comp-scenario", type=str, default="stress",
                        help="Inner scenario for comparison test (default: stress)")
    parser.add_argument("--list-mcus", action="store_true",
                        help="List all supported MCUs and their Flash configurations")
    parser.add_argument("--dump", action="store_true",
                        help="Dump Flash state after test")
    parser.add_argument("--output", type=str, default=None,
                        help="Save results to JSON file")
    parser.add_argument("--viz", action="store_true",
                        help="Generate interactive HTML visualizer after test")
    parser.add_argument("--viz-output", type=str, default=None,
                        help="Visualizer HTML output path (default: auto-named)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")

    args = parser.parse_args()

    if args.list_mcus:
        print("\nSupported STM32 MCUs:")
        print("=" * 60)
        for name, mcu in MCU_DATABASE.items():
            print(f"\n{name}: {mcu.name}")
            print(f"  Flash: {mcu.flash_size // 1024} KB")
            print(f"  Sectors: {len(mcu.sectors)}")
            print(f"  Program unit: {mcu.program_unit} bytes")
            print(f"  Dual-bank: {mcu.dual_bank}")
            print(f"  Cache flush needed: {mcu.cache_flush_needed}")
            for sector in mcu.sectors:
                print(f"    {sector.name}: 0x{sector.base_addr:08X} ({sector.size // 1024} KB)")
        return

    mode = DriverMode.BUGGY if args.mode == "buggy" else DriverMode.FIXED
    scenario = SCENARIOS[args.scenario]

    print(f"\n{'='*60}")
    print(f"STM32 Flash Wear-Leveling Simulator")
    print(f"MCU: {args.mcu} | Scenario: {args.scenario} | Mode: {args.mode.upper()}")
    print(f"{'='*60}\n")

    # Run scenario
    kwargs = {
        "num_writes": args.writes,
        "num_iterations": args.faults,
        "cut_probability": args.prob,
        "phase": args.phase,
        "scenario_name": args.comp_scenario,
    }

    try:
        results = scenario.run(args.mcu, mode, **kwargs)

        # Print results
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)
        print(json.dumps(results, indent=2, default=str))

        # Dump state if requested
        if args.dump and args.scenario not in ("comparison", "sector_mapping"):
            # Need to recreate for dump (scenario.run doesn't return driver)
            print("\n[Note: Use --verbose for detailed state during test]")

        # Save to file
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"\nResults saved to {args.output}")

        # Generate HTML visualizer if requested
        if args.viz:
            viz_path = args.viz_output or f"wl_viz_{args.mcu}_{args.mode}.html"
            generate_viz_html(args.mcu, args.mode, viz_path)
            abs_viz = os.path.abspath(viz_path)
            print(f"\n🌐 Visualizer generated: {abs_viz}")
            print(f"   Open in browser: file://{abs_viz}")

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()