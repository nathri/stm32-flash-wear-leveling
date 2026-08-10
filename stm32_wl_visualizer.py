#!/usr/bin/env python3
"""
STM32 Flash Wear-Leveling Visualizer
======================================
Generates an interactive HTML visualization of Flash wear-leveling state.
Can be used standalone or integrated with the simulator CLI.

Usage:
    python stm32_wl_visualizer.py --mcu STM32F401 --mode fixed --output viz.html
    python stm32_wl_visualizer.py --from-json results.json --output viz.html
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STM32 Flash Wear-Leveling Visualizer</title>
<style>
  :root {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --border: #30363d; --text: #c9d1d9; --text2: #8b949e; --text3: #484f58;
    --accent: #58a6ff; --ok: #3fb950; --warn: #d29922; --err: #f85149;
    --chart1: #58a6ff; --chart2: #f85149; --chart3: #3fb950; --chart4: #a371f7;
    --font: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
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
  .page-card {
    border:1px solid var(--border); border-radius:10px; padding:14px; background:var(--bg2);
    transition:border-color 0.15s;
  }
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
  .rec-cell {
    width:24px; height:24px; border-radius:4px; display:flex; align-items:center; justify-content:center;
    font-size:9px; font-weight:600; cursor:default; border:1px solid var(--border); position:relative;
  }
  .rec-cell.valid { background:var(--text); color:var(--bg); border-color:var(--text); }
  .rec-cell.deleted { background:rgba(248,81,73,0.12); color:var(--err); border-color:var(--err); }
  .rec-cell.empty { background:transparent; color:var(--text3); }
  .rec-cell:hover::after {
    content:attr(data-tip); position:absolute; bottom:28px; left:50%; transform:translateX(-50%);
    background:var(--text); color:var(--bg); padding:4px 10px; border-radius:6px; font-size:11px;
    white-space:nowrap; z-index:10; pointer-events:none; font-family:var(--font);
  }

  .stats-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:20px; }
  @media(max-width:640px){ .stats-grid { grid-template-columns:repeat(2,1fr); } }
  .stat-box { border:1px solid var(--border); border-radius:10px; padding:14px; text-align:center; background:var(--bg2); }
  .stat-value { font-size:26px; font-weight:600; font-variant-numeric:tabular-nums; }
  .stat-label { font-size:11px; color:var(--text2); margin-top:4px; }

  .log-panel {
    border:1px solid var(--border); border-radius:10px; padding:12px 14px;
    max-height:180px; overflow-y:auto; font-size:12px; font-family:var(--mono); line-height:1.6; background:var(--bg2);
  }
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
  <div class="subtitle">Interactive simulation — {{MCU_NAME}} — {{MODE}} mode</div>

  <div class="toolbar">
    <span id="mode-badge" class="badge {{MODE_CLASS}}">{{MODE}}</span>
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
  const HEADER_SIZE = 16;
  const RECORD_SIZE = 32;
  const MAGIC = 0xDEADBEEF;
  const IS_BUGGY = {{IS_BUGGY}};

  class FlashMem {
    constructor(cfg) {
      this.cfg = cfg;
      this.mem = new Map();
      this.eraseCounts = {};
      cfg.sectors.forEach(s => this.eraseCounts[s.n] = 0);
      this._init();
    }
    _init() {
      this.cfg.sectors.forEach(s => {
        for (let i = 0; i < s.size; i++) this.mem.set(s.addr + i, 0xFF);
      });
    }
    sectorOf(addr) {
      return this.cfg.sectors.find(s => s.addr <= addr && addr < s.addr + s.size);
    }
    read(addr, len) {
      const b = [];
      for (let i = 0; i < len; i++) b.push(this.mem.get(addr + i) ?? 0xFF);
      return b;
    }
    programWord(addr, val, size = 4) {
      const sec = this.sectorOf(addr);
      if (!sec) throw new Error("Out of flash");
      if (addr % size !== 0) throw new Error("Unaligned");
      for (let i = 0; i < size; i++) {
        const a = addr + i, old = this.mem.get(a) ?? 0xFF, nv = (val >> (8 * i)) & 0xFF;
        this.mem.set(a, old & nv);
      }
    }
    eraseSector(n) {
      const sec = this.cfg.sectors.find(s => s.n === n);
      if (!sec) throw new Error("Bad sector");
      for (let i = 0; i < sec.size; i++) this.mem.set(sec.addr + i, 0xFF);
      this.eraseCounts[n]++;
    }
  }

  class WLDriver {
    constructor(flash, pageAddrs, buggy) {
      this.flash = flash;
      this.pageAddrs = [...pageAddrs];
      this.buggy = buggy;
      this.pageCount = pageAddrs.length;
      this.pageSize = flash.cfg.pageSize;
      this.activeIdx = -1;
      this.seq = 0;
      this.nextOff = {};
      this.stats = { writes: 0, reads: 0, deletes: 0, gc: 0, powerCuts: 0, dataLoss: 0, corrupt: 0 };
      this._init();
    }
    _init() {
      for (let i = 0; i < this.pageCount; i++) {
        this.nextOff[i] = HEADER_SIZE;
        const h = this._readHeader(i);
        if (h.magic === MAGIC && h.status === 0xABCD) {
          if (this.buggy) { if (this.activeIdx < 0) { this.activeIdx = i; this.seq = h.seq; } }
          else { if (this.activeIdx < 0 || h.seq > this.seq) { this.activeIdx = i; this.seq = h.seq; } }
        }
      }
      if (this.activeIdx < 0) this._formatAll();
    }
    _readHeader(pi) {
      const b = this.flash.read(this.pageAddrs[pi], 16);
      return {
        magic: (b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24),
        erase: (b[4] | b[5] << 8 | b[6] << 16 | b[7] << 24),
        status: (b[8] | b[9] << 8),
        seq: (b[10] | b[11] << 8 | b[12] << 16 | b[13] << 24)
      };
    }
    _writeHeader(pi, status, eraseCount) {
      const addr = this.pageAddrs[pi];
      const words = [MAGIC, eraseCount, (status & 0xFFFF) | ((this.seq & 0xFFFF) << 16), (this.seq >>> 16) | 0xFFFF0000];
      words.forEach((w, i) => this.flash.programWord(addr + i * 4, w, 4));
    }
    _formatAll() {
      this.pageAddrs.forEach((a, i) => {
        const s = this.flash.sectorOf(a);
        if (s) this.flash.eraseSector(s.n);
        this.nextOff[i] = HEADER_SIZE;
      });
      this.activeIdx = 0; this.seq = 1;
      this._writeHeader(0, 0xABCD, 0);
    }
    _recordsOf(pi) {
      const addr = this.pageAddrs[pi], recs = [];
      for (let off = HEADER_SIZE; off + RECORD_SIZE <= this.pageSize; off += RECORD_SIZE) {
        const b = this.flash.read(addr + off, RECORD_SIZE);
        const id = b[0] | b[1] << 8, len = b[2] | b[3] << 8, cs = b[4] | b[5] << 8;
        const data = b.slice(6, 30);
        if (id !== 0xFFFF && len !== 0xFFFF && len <= 24) {
          recs.push({ off, id, len, cs, data, deleted: len === 0 });
        }
      }
      return recs;
    }
    _findRec(pi, rid) {
      const recs = this._recordsOf(pi).filter(r => r.id === rid && !r.deleted);
      if (!recs.length) return null;
      return this.buggy ? recs[0] : recs[recs.length - 1];
    }
    writeRecord(id, dataBytes) {
      this.stats.writes++;
      const db = dataBytes.slice(0, 24);
      const padded = [...db, ...Array(24 - db.length).fill(0)];
      if (this.buggy) this._delInternal(id);
      if (this.nextOff[this.activeIdx] + RECORD_SIZE > this.pageSize) {
        if (!this._gc()) { app.log("GC failed — page full", "err"); return false; }
      }
      const addr = this.pageAddrs[this.activeIdx] + this.nextOff[this.activeIdx];
      const rec = [id & 0xFF, (id >> 8) & 0xFF, db.length & 0xFF, (db.length >> 8) & 0xFF, 0, 0, ...padded];
      for (let i = 0; i < 32; i += 4) {
        const w = rec[i] | rec[i + 1] << 8 | rec[i + 2] << 16 | rec[i + 3] << 24;
        this.flash.programWord(addr + i, w, 4);
      }
      this.nextOff[this.activeIdx] += RECORD_SIZE;
      if (!this.buggy) this._delInternal(id, true);
      return true;
    }
    readRecord(id) {
      this.stats.reads++;
      if (this.activeIdx >= 0) {
        const r = this._findRec(this.activeIdx, id);
        if (r) return r.data.slice(0, r.len);
      }
      for (let i = 0; i < this.pageCount; i++) {
        if (i === this.activeIdx) continue;
        const r = this._findRec(i, id);
        if (r) return r.data.slice(0, r.len);
      }
      return null;
    }
    _delInternal(id, skipActive = false) {
      for (let i = 0; i < this.pageCount; i++) {
        if (skipActive && i === this.activeIdx) continue;
        const addr = this.pageAddrs[i];
        for (let off = HEADER_SIZE; off + RECORD_SIZE <= this.pageSize; off += RECORD_SIZE) {
          const b = this.flash.read(addr + off, RECORD_SIZE);
          const rid = b[0] | b[1] << 8, len = b[2] | b[3] << 8;
          if (rid === id && len !== 0xFFFF && len !== 0) {
            const delAddr = addr + off + 2;
            if (this.buggy) {
              try { this.flash.programWord(delAddr, 0x0000FFFF, 4); } catch (e) { }
            } else {
              this.flash.programWord(delAddr & ~0x3, 0x0000FFFF, 4);
            }
            return true;
          }
        }
      }
      return false;
    }
    deleteRecord(id) { this.stats.deletes++; return this._delInternal(id); }
    _gc() {
      this.stats.gc++;
      const src = this.activeIdx;
      let dst = -1;
      for (let i = 0; i < this.pageCount; i++) {
        if (i === src) continue;
        const h = this._readHeader(i);
        if (h.magic !== MAGIC || h.status === 0xFFFF) { dst = i; break; }
      }
      if (dst < 0) return false;
      const recs = this._recordsOf(src).filter(r => !r.deleted);
      this.seq++;
      if (this.buggy) {
        let off = HEADER_SIZE;
        recs.forEach(r => {
          const a = this.pageAddrs[dst] + off;
          const b = [r.id & 0xFF, (r.id >> 8) & 0xFF, r.len & 0xFF, (r.len >> 8) & 0xFF, r.cs & 0xFF, (r.cs >> 8) & 0xFF, ...r.data];
          for (let i = 0; i < 32; i += 4) this.flash.programWord(a + i, b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24, 4);
          off += RECORD_SIZE;
        });
        this.nextOff[dst] = off;
        this._writeHeader(src, 0xFFFF, this._readHeader(src).erase);
        const ss = this.flash.sectorOf(this.pageAddrs[src]);
        if (ss) this.flash.eraseSector(ss.n);
        this._writeHeader(dst, 0xABCD, this._readHeader(src).erase + 1);
        this.activeIdx = dst;
      } else {
        this._writeHeader(dst, 0xCDEF, this._readHeader(dst).erase);
        let off = HEADER_SIZE;
        recs.forEach(r => {
          const a = this.pageAddrs[dst] + off;
          const b = [r.id & 0xFF, (r.id >> 8) & 0xFF, r.len & 0xFF, (r.len >> 8) & 0xFF, r.cs & 0xFF, (r.cs >> 8) & 0xFF, ...r.data];
          for (let i = 0; i < 32; i += 4) this.flash.programWord(a + i, b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24, 4);
          off += RECORD_SIZE;
        });
        this.nextOff[dst] = off;
        this._writeHeader(dst, 0xABCD, this._readHeader(dst).erase + 1);
        this._writeHeader(src, 0xFFFF, this._readHeader(src).erase);
        const ss = this.flash.sectorOf(this.pageAddrs[src]);
        if (ss) this.flash.eraseSector(ss.n);
        this.activeIdx = dst;
        if (this.nextOff[dst] + RECORD_SIZE > this.pageSize) return false;
      }
      return true;
    }
  }

  const app = {
    mcuKey: "{{MCU_KEY}}",
    buggy: IS_BUGGY,
    flash: null,
    driver: null,
    recId: 1,

    init() {
      this.reset();
      document.getElementById("write-input").addEventListener("keydown", e => { if (e.key === "Enter") this.writeRecord(); });
    },

    reset() {
      const cfg = MCU_CFG;
      this.flash = new FlashMem(cfg);
      const addrs = cfg.wlSectors.map(si => cfg.sectors[si].addr);
      this.driver = new WLDriver(this.flash, addrs, this.buggy);
      this.recId = 1;
      this.render();
      this.log(`Reset: ${cfg.name}, ${cfg.wlSectors.length} pages × ${cfg.pageSize / 1024}KB`);
    },

    writeRecord() {
      const inp = document.getElementById("write-input");
      const text = inp.value.trim() || `rec_${this.recId}`;
      const bytes = text.split("").map(c => c.charCodeAt(0) & 0xFF);
      const ok = this.driver.writeRecord(this.recId, bytes);
      if (ok) {
        this.log(`Write ID=${this.recId} "${text}" → OK`);
        this.recId++;
        inp.value = "";
      } else {
        this.log(`Write ID=${this.recId} FAILED`, "err");
      }
      this.render();
    },

    gc() {
      const ok = this.driver._gc();
      this.log(`GC → ${ok ? "OK" : "FAILED"}`, ok ? "ok" : "err");
      this.render();
    },

    powerCut() {
      this.driver.stats.powerCuts++;
      const cfg = MCU_CFG;
      const addrs = cfg.wlSectors.map(si => cfg.sectors[si].addr);
      this.driver = new WLDriver(this.flash, addrs, this.buggy);
      this.log("⚡ Power cut — rebooted", "warn");
      this.render();
    },

    exportState() {
      const state = {
        mcu: this.mcuKey,
        mode: this.buggy ? "buggy" : "fixed",
        stats: this.driver.stats,
        pages: []
      };
      for (let i = 0; i < this.driver.pageCount; i++) {
        const h = this.driver._readHeader(i);
        const sec = this.flash.sectorOf(this.driver.pageAddrs[i]);
        state.pages.push({
          index: i,
          address: `0x${this.driver.pageAddrs[i].toString(16).toUpperCase().padStart(8, "0")}`,
          status: h.status === 0xABCD ? "ACTIVE" : h.status === 0xCDEF ? "COPYING" : h.status === 0xFFFF ? "ERASED" : "UNKNOWN",
          eraseCount: this.flash.eraseCounts[sec ? sec.n : 0],
          sequence: h.seq,
          records: this.driver._recordsOf(i).map(r => ({
            id: r.id, len: r.len, deleted: r.deleted,
            data: String.fromCharCode(...r.data.slice(0, r.len)).replace(/[^\x20-\x7E]/g, ".")
          }))
        });
      }
      const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `wl_state_${this.mcuKey}_${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      this.log("State exported to JSON", "ok");
    },

    log(msg, cls = "info") {
      const el = document.getElementById("log");
      const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
      const line = document.createElement("div");
      line.className = "log-line";
      line.innerHTML = `<span class="ts">${ts}</span><span class="${cls}">${msg}</span>`;
      el.appendChild(line);
      el.scrollTop = el.scrollHeight;
      while (el.children.length > 60) el.removeChild(el.firstChild);
    },

    render() {
      this.renderSectors();
      this.renderPages();
      this.renderStats();
    },

    renderSectors() {
      const cfg = MCU_CFG;
      const wlSet = new Set(cfg.wlSectors);
      const maxSize = Math.max(...cfg.sectors.map(s => s.size));
      const container = document.getElementById("sector-map");
      container.innerHTML = '<div class="sector-title">Flash sector map</div>';
      cfg.sectors.forEach((s, idx) => {
        const isWl = wlSet.has(idx);
        const row = document.createElement("div");
        row.className = "sector-row";
        row.innerHTML = `<div class="sector-name">${s.name}</div>
          <div class="sector-bar-wrap">
            <div class="sector-bar ${isWl ? "wl" : "code"}" style="width:${(s.size / maxSize * 100).toFixed(1)}%"></div>
          </div>
          <div class="sector-size">${s.size / 1024}KB</div>`;
        container.appendChild(row);
      });
    },

    renderPages() {
      const container = document.getElementById("pages");
      container.innerHTML = "";
      for (let i = 0; i < this.driver.pageCount; i++) {
        const h = this.driver._readHeader(i);
        const recs = this.driver._recordsOf(i);
        const valid = recs.filter(r => !r.deleted);
        const totalSlots = Math.floor((this.driver.pageSize - HEADER_SIZE) / RECORD_SIZE);
        const isActive = i === this.driver.activeIdx;
        let statusName = "ERASED";
        if (h.status === 0xABCD) statusName = "ACTIVE";
        else if (h.status === 0xCDEF) statusName = "COPYING";
        else if (h.magic === MAGIC && h.status !== 0xFFFF) statusName = "FULL";
        const sec = this.flash.sectorOf(this.driver.pageAddrs[i]);
        const eraseCnt = this.flash.eraseCounts[sec ? sec.n : 0];
        const card = document.createElement("div");
        card.className = "page-card" + (isActive ? " active" : "");
        card.innerHTML = `<div class="page-header">
          <div class="page-title">Page ${i} @ 0x${this.driver.pageAddrs[i].toString(16).toUpperCase().padStart(8, "0")}</div>
          <div class="page-status ${statusName}">${statusName}</div>
        </div>
        <div class="page-meta">Erase count: ${eraseCnt} | Records: ${valid.length}/${totalSlots} | Seq: ${h.seq}</div>
        <div class="records-grid" id="recs-${i}"></div>`;
        container.appendChild(card);
        const recContainer = card.querySelector(`#recs-${i}`);
        for (let slot = 0; slot < totalSlots; slot++) {
          const rec = recs[slot];
          const el = document.createElement("div");
          el.className = "rec-cell " + (rec ? (rec.deleted ? "deleted" : "valid") : "empty");
          if (rec && !rec.deleted) {
            const txt = String.fromCharCode(...rec.data.slice(0, rec.len)).replace(/[^\x20-\x7E]/g, ".");
            el.textContent = rec.id;
            el.setAttribute("data-tip", `ID:${rec.id} len:${rec.len} "${txt}"`);
          } else if (rec && rec.deleted) {
            el.textContent = "×";
            el.setAttribute("data-tip", `ID:${rec.id} DELETED`);
          } else {
            el.textContent = "·";
            el.setAttribute("data-tip", "empty");
          }
          recContainer.appendChild(el);
        }
      }
    },

    renderStats() {
      const s = this.driver.stats;
      const grid = document.getElementById("stats");
      const items = [
        { v: s.writes, l: "Writes", color: "" },
        { v: s.gc, l: "GC cycles", color: "" },
        { v: s.powerCuts, l: "Power cuts", color: s.powerCuts ? "color:var(--warn)" : "" },
        { v: s.reads, l: "Reads", color: "" },
      ];
      grid.innerHTML = items.map(it => `<div class="stat-box"><div class="stat-value" style="${it.color}">${it.v}</div><div class="stat-label">${it.l}</div></div>`).join("");
    }
  };

  app.init();
  window.app = app;
})();
</script>
</body>
</html>
"""

MCU_DATABASE = {
    "STM32F401": {
        "name": "STM32F401RE",
        "flash_size": 256 * 1024,
        "pageSize": 16 * 1024,
        "sectors": [
            {"n": 0, "name": "S0", "addr": 0x08000000, "size": 16 * 1024},
            {"n": 1, "name": "S1", "addr": 0x08004000, "size": 16 * 1024},
            {"n": 2, "name": "S2", "addr": 0x08008000, "size": 16 * 1024},
            {"n": 3, "name": "S3", "addr": 0x0800C000, "size": 16 * 1024},
            {"n": 4, "name": "S4", "addr": 0x08010000, "size": 64 * 1024},
            {"n": 5, "name": "S5", "addr": 0x08020000, "size": 128 * 1024},
        ],
        "wlSectors": [1, 2],
    },
    "STM32F767_DUAL": {
        "name": "STM32F767ZI Dual-Bank",
        "flash_size": 1024 * 1024,
        "pageSize": 128 * 1024,
        "sectors": [
            {"n": 0, "name": "S0", "addr": 0x08000000, "size": 16 * 1024},
            {"n": 1, "name": "S1", "addr": 0x08004000, "size": 16 * 1024},
            {"n": 2, "name": "S2", "addr": 0x08008000, "size": 16 * 1024},
            {"n": 3, "name": "S3", "addr": 0x0800C000, "size": 16 * 1024},
            {"n": 4, "name": "S4", "addr": 0x08010000, "size": 64 * 1024},
            {"n": 5, "name": "S5", "addr": 0x08020000, "size": 128 * 1024},
            {"n": 6, "name": "S6", "addr": 0x08040000, "size": 128 * 1024},
            {"n": 7, "name": "S7", "addr": 0x08060000, "size": 128 * 1024},
            {"n": 12, "name": "S12", "addr": 0x08080000, "size": 16 * 1024},
            {"n": 13, "name": "S13", "addr": 0x08084000, "size": 16 * 1024},
            {"n": 14, "name": "S14", "addr": 0x08088000, "size": 16 * 1024},
            {"n": 15, "name": "S15", "addr": 0x0808C000, "size": 16 * 1024},
            {"n": 16, "name": "S16", "addr": 0x08090000, "size": 64 * 1024},
            {"n": 17, "name": "S17", "addr": 0x080A0000, "size": 128 * 1024},
            {"n": 18, "name": "S18", "addr": 0x080C0000, "size": 128 * 1024},
            {"n": 19, "name": "S19", "addr": 0x080E0000, "size": 128 * 1024},
        ],
        "wlSectors": [5, 6],
    },
    "STM32F767_SINGLE": {
        "name": "STM32F767ZI Single-Bank",
        "flash_size": 1024 * 1024,
        "pageSize": 256 * 1024,
        "sectors": [
            {"n": 0, "name": "S0", "addr": 0x08000000, "size": 32 * 1024},
            {"n": 1, "name": "S1", "addr": 0x08008000, "size": 32 * 1024},
            {"n": 2, "name": "S2", "addr": 0x08010000, "size": 32 * 1024},
            {"n": 3, "name": "S3", "addr": 0x08018000, "size": 32 * 1024},
            {"n": 4, "name": "S4", "addr": 0x08020000, "size": 128 * 1024},
            {"n": 5, "name": "S5", "addr": 0x08040000, "size": 256 * 1024},
            {"n": 6, "name": "S6", "addr": 0x08080000, "size": 256 * 1024},
            {"n": 7, "name": "S7", "addr": 0x080C0000, "size": 256 * 1024},
        ],
        "wlSectors": [5, 6],
    },
}


def generate_html(mcu_key: str, mode: str, output_path: str) -> str:
    """Generate standalone HTML visualizer for the given MCU and mode."""
    mcu = MCU_DATABASE[mcu_key]
    mcu_json = json.dumps(mcu)

    html = HTML_TEMPLATE
    html = html.replace("{{MCU_NAME}}", mcu["name"])
    html = html.replace("{{MCU_KEY}}", mcu_key)
    html = html.replace("{{MODE}}", mode)
    html = html.replace("{{MODE_CLASS}}", mode)
    html = html.replace("{{MCU_JSON}}", mcu_json)
    html = html.replace("{{IS_BUGGY}}", "true" if mode == "buggy" else "false")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate interactive HTML visualizer for STM32 Flash wear-leveling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate visualizer for STM32F401 (fixed mode)
  python stm32_wl_visualizer.py --mcu STM32F401 --mode fixed --output viz.html

  # Generate visualizer for STM32F767 (buggy mode)
  python stm32_wl_visualizer.py --mcu STM32F767_DUAL --mode buggy --output viz_f767.html

  # Generate and open in browser automatically
  python stm32_wl_visualizer.py --mcu STM32F401 --mode fixed --open
        """
    )
    parser.add_argument("--mcu", type=str, default="STM32F401",
                        choices=list(MCU_DATABASE.keys()),
                        help="Target MCU (default: STM32F401)")
    parser.add_argument("--mode", type=str, default="fixed",
                        choices=["buggy", "fixed"],
                        help="Driver mode (default: fixed)")
    parser.add_argument("--output", type=str, default="stm32_wl_visualizer.html",
                        help="Output HTML file path (default: stm32_wl_visualizer.html)")
    parser.add_argument("--open", action="store_true",
                        help="Open the generated HTML in default browser")

    args = parser.parse_args()

    output_path = generate_html(args.mcu, args.mode, args.output)
    abs_path = os.path.abspath(output_path)

    print(f"✅ Visualizer generated: {abs_path}")
    print(f"   MCU: {MCU_DATABASE[args.mcu]['name']}")
    print(f"   Mode: {args.mode}")
    print(f"   Size: {os.path.getsize(output_path) / 1024:.1f} KB")

    if args.open:
        webbrowser.open(f"file://{abs_path}")
        print("🌐 Opened in browser")
    else:
        print(f"\nOpen with: python -m webbrowser {output_path}")
        print(f"Or:        open file://{abs_path}")


if __name__ == "__main__":
    main()