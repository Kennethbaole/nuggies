// glint stage: read-only display of the companion app's /api/state.
// Falls back to a clearly labelled demo when the app can't be reached.
(function () {
  "use strict";
  var CX = 400, CY = 260, ORX = 292, ORY = 200, IRX = 138, IRY = 92, MRX = 216, MRY = 147;
  var N = 8, SEG = 2 * Math.PI / N;
  var $ = function (id) { return document.getElementById(id); };

  (function grain() {
    try {
      var c = document.createElement("canvas"); c.width = c.height = 220;
      var g = c.getContext("2d"), img = g.createImageData(220, 220);
      for (var i = 0; i < img.data.length; i += 4) {
        var v = Math.random() * 255 | 0;
        img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255;
      }
      g.putImageData(img, 0, 0);
      $("grain").style.backgroundImage = "url(" + c.toDataURL() + ")";
    } catch (e) {}
  })();

  function pt(rx, ry, a) { return [CX + rx * Math.cos(a), CY + ry * Math.sin(a)]; }
  function wedgePath(k) {
    var a0 = -Math.PI / 2 + k * SEG - SEG / 2, a1 = a0 + SEG, steps = 12, d = "", i, a, p;
    for (i = 0; i <= steps; i++) { a = a0 + (a1 - a0) * i / steps; p = pt(ORX - 6, ORY - 6, a); d += (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }
    for (i = steps; i >= 0; i--) { a = a0 + (a1 - a0) * i / steps; p = pt(IRX + 6, IRY + 6, a); d += "L" + p[0].toFixed(1) + " " + p[1].toFixed(1); }
    return d + "Z";
  }

  var slotEls = [];
  (function buildSlots() {
    var g = $("slots");
    for (var k = 0; k < N; k++) {
      var p = pt(MRX, MRY, -Math.PI / 2 + k * SEG);
      var t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", p[0].toFixed(1)); t.setAttribute("y", p[1].toFixed(1));
      t.setAttribute("text-anchor", "middle"); t.setAttribute("dominant-baseline", "central");
      t.setAttribute("class", "slot");
      g.appendChild(t); slotEls.push(t);
    }
  })();

  var PHASES = {
    centering: "Look straight ahead",
    ready: "Ready",
    recovery: "Return to centre",
    retry: "Look centre and try again",
    signal_lost: "Check the electrodes"
  };
  var MODES = { demo: "Keyboard", keyboard: "Keyboard", serial: "Eyes", scenario: "Replay", replay: "Replay" };

  function chip(id, text, cls) {
    var el = $(id);
    el.lastElementChild.textContent = text;
    el.className = "chip" + (cls ? " " + cls : "");
  }

  var lastSpoken = null;
  function render(s, source) {
    var slots = Array.isArray(s.slots) ? s.slots : [];
    // Under eye control the app parks `selected` on a default slot; only a detected choice is a real highlight.
    var sel = typeof s.selected === "number" && (s.wheel_test || s.eog_communication ? s.eog_choice_pending === true : true) ? s.selected : -1;
    for (var k = 0; k < N; k++) {
      var slot = slots[k] || { label: "", enabled: false };
      slotEls[k].textContent = /^[—–-]?$/.test(slot.label || "") ? "" : slot.label;
      slotEls[k].setAttribute("class", "slot" + (slot.enabled === false ? " off" : "") + (k === sel ? " sel" : ""));
    }
    var wedge = $("wedge");
    if (sel >= 0 && sel < N && slots[sel]) { wedge.setAttribute("d", wedgePath(sel)); wedge.setAttribute("opacity", ".95"); }
    else { wedge.setAttribute("opacity", "0"); }

    var spelling = s.screen === "spell" && s.draft;
    $("centre").textContent = spelling || (slots[sel] && slots[sel].label) || "";
    $("preview").textContent = s.preview && sel >= 0 ? "“" + s.preview + "”" : "";

    var eyes = s.eog_communication === true;
    $("hint").textContent = eyes ? (s.eog_confirmation_ready ? "double blink" : (s.eog_choice_pending ? "return to centre" : "")) : (sel >= 0 ? "select to speak" : "");
    var phase = (s.gaze_hover && s.gaze_hover.phase) || "ready";
    $("phase").textContent = s.connected === false ? "Signal paused" : (eyes ? (PHASES[phase] || "Ready") : "Ready");
    $("note").textContent = (eyes && s.eog_confirmation) || "Glance to choose · return to centre · double blink to speak";

    var heard = s.heard || "";
    $("said").textContent = heard ? "“" + heard + "”" : "Waiting for someone to speak";
    var spoken = s.confirmed || "";
    if (spoken !== lastSpoken) {
      var sp = $("spoken");
      sp.textContent = spoken || "Nothing spoken yet";
      sp.classList.remove("fresh"); void sp.offsetWidth; if (spoken) sp.classList.add("fresh");
      lastSpoken = spoken;
    }

    chip("chip-source", source === "live" ? "Live" : "Demo data", source === "live" ? "on" : "");
    chip("chip-link", s.connected === false ? "Signal paused" : "Signal ok", s.connected === false ? "warn" : "on");
    chip("chip-mode", eyes ? "Eyes" : (MODES[s.input_mode] || "Keyboard"), eyes ? "on" : "");
    $("ringwrap").style.setProperty("--glow-on", s.connected === false ? ".4" : ".95");
  }

  // ---------- Live: poll the companion app ----------
  var token = "";
  try { token = new URLSearchParams(location.search).get("token") || sessionStorage.getItem("nuggies-token") || ""; } catch (e) {}
  var live = false, misses = 0, demoTimer = null;
  function poll() {
    fetch("/api/state", { headers: token ? { Authorization: "Bearer " + token } : {}, cache: "no-store" })
      .then(function (r) {
        if (r.status === 401) throw new Error("auth");
        if (!r.ok) throw new Error("http");
        return r.json();
      })
      .then(function (s) {
        if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
        live = true; misses = 0; render(s, "live"); setTimeout(poll, 250);
      })
      .catch(function (e) {
        misses++;
        if (live && misses < 8) { setTimeout(poll, 500); return; }
        live = false; startDemo();
        if (e && e.message === "auth") $("note").textContent = "Add ?token=YOUR_APP_TOKEN to this page's address";
        setTimeout(poll, 3000);
      });
  }

  // ---------- Demo: a scripted exchange, labelled "Demo data" ----------
  function startDemo() {
    if (demoTimer) return;
    var script = [
      { heard: "Hey, how are you feeling today?", replies: [["Better", "Better than yesterday, honestly."], ["Tired", "A little tired today."], ["Pain", "My back hurts a bit."], ["Stay", "Could you stay a while?"]], pick: 0 },
      { heard: "Do you want me to open the window?", replies: [["Yes", "Yes please, some air would be nice."], ["No", "No thanks."], ["Later", "Maybe later. It's a little cold."], ["Cold", "I'm cold right now."]], pick: 2 },
      { heard: "Your sister called this morning.", replies: [["Call her", "Can we call her back after lunch?"], ["Tired", "Tell her I'm resting."], ["Love", "Tell her I love her."], ["Thanks", "Thanks for letting me know."]], pick: 0 }
    ];
    var layout = [0, 2, 6, 5];
    var step = 0, beat = 0, said = "";
    function frame() {
      var sc = script[step % script.length];
      var slots = [];
      for (var k = 0; k < N; k++) slots.push({ label: k === 4 ? "Back" : "", text: "", enabled: k === 4 });
      sc.replies.forEach(function (r, i) { slots[layout[i]] = { label: r[0], text: r[1], enabled: true }; });
      var s = { slots: slots, connected: true, input_mode: "serial", eog_communication: true, heard: sc.heard, confirmed: said, selected: -1, gaze_hover: { phase: "ready" } };
      if (beat === 1) { s.selected = layout[(sc.pick + 1) % 4]; s.eog_choice_pending = true; s.gaze_hover.phase = "recovery"; }
      if (beat === 2) { s.selected = layout[sc.pick]; s.eog_choice_pending = true; s.gaze_hover.phase = "recovery"; }
      if (beat === 3) { s.selected = layout[sc.pick]; s.eog_choice_pending = true; s.eog_confirmation_ready = true; s.eog_confirmation = "Double blink to choose " + sc.replies[sc.pick][0]; }
      if (beat === 4) { said = sc.replies[sc.pick][1]; s.confirmed = said; s.selected = layout[sc.pick]; s.eog_choice_pending = true; s.eog_confirmation = "Selected"; }
      if (s.selected >= 0) s.preview = slots[s.selected].text;
      render(s, "demo");
      beat++; if (beat > 5) { beat = 0; step++; }
    }
    frame();
    demoTimer = setInterval(frame, 1600);
  }

  if (location.protocol === "http:" || location.protocol === "https:") poll(); else startDemo();
})();
