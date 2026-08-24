/* PROTOTYPE — THROWAWAY. */
import { buildApkg, stableId, guidFor } from './apkg.js';

const $ = (id) => document.getElementById(id);
const log = (msg) => {
  $('log').textContent += msg + '\n';
  $('log').scrollTop = $('log').scrollHeight;
  console.log(msg);
};
const mb = (n) => (n / 1048576).toFixed(1) + ' MB';
const heap = () => (performance.memory
  ? ` heap ${mb(performance.memory.usedJSHeapSize)}/${mb(performance.memory.jsHeapSizeLimit)}`
  : '');

// The CLI derives both from a seed string; reproduce it exactly.
const DECK_SEED = 'US-MA';
const DECK_ID = stableId(DECK_SEED);
const DECK_NAME = 'AviAnki – US-MA';
// A build timestamp fixed on purpose, so a browser build and a CLI build of
// the same catalog are comparable byte for byte.
const TIMESTAMP = 1700000000;

// --- prototype-only note type: the randomised-audio experiment ------------
const RANDOM_AUDIO_MODEL = {
  id: stableId('PROTOTYPE_RandomAudio_v1'),
  name: 'PROTOTYPE – Random audio',
  fields: [{ name: 'BirdName' }, { name: 'SciName' },
           { name: 'Snd1' }, { name: 'Snd2' }, { name: 'Snd3' },
           { name: 'File1' }, { name: 'File2' }, { name: 'File3' }],
  css: '.card{font-family:Georgia,serif;font-size:16px;padding:16px}' +
       '#diag{font-family:monospace;font-size:11px;white-space:pre-wrap;' +
       'background:#eee;padding:8px;margin-top:12px;word-break:break-all}',
  templates: [
    {
      // Variant A — three [sound:] tags. Anki substitutes these before any
      // template JS runs, so JS can only manipulate whatever it produced.
      name: 'A · sound-tag',
      qfmt: `<div class="card">
<div>Variant A — three <code>[sound:]</code> tags</div>
<div id="snd">{{Snd1}} {{Snd2}} {{Snd3}}</div>
<div id="diag">JS DID NOT RUN</div>
<script>
(function(){
  var box=document.getElementById('snd'), d=document.getElementById('diag');
  var nodes=box.querySelectorAll('a,audio,button,.replay-button,.replaybutton,.soundLink');
  var pick=nodes.length?Math.floor(Math.random()*nodes.length):-1;
  for(var i=0;i<nodes.length;i++){ if(i!==pick) nodes[i].style.display='none'; }
  d.textContent='player nodes found: '+nodes.length+'\\nshowing #'+(pick+1)
    +'\\nraw DOM after Anki substitution:\\n'+box.innerHTML;
})();
</script>
</div>`,
      afmt: `<div class="card"><b>{{BirdName}}</b><br><i>{{SciName}}</i>
<div>{{Snd1}} {{Snd2}} {{Snd3}}</div></div>`,
    },
    {
      // Variant B — plain HTML5 <audio>, src chosen by JS at render time.
      name: 'B · html-audio',
      qfmt: `<div class="card">
<div>Variant B — HTML5 &lt;audio&gt;, source chosen by JS</div>
<div id="ha"></div>
<div id="diag">JS DID NOT RUN</div>
<script>
(function(){
  var d=document.getElementById('diag');
  var files=['{{File1}}','{{File2}}','{{File3}}'].filter(function(f){return f;});
  if(!files.length){ d.textContent='no files'; return; }
  var pick=files[Math.floor(Math.random()*files.length)];
  var a=document.createElement('audio');
  a.controls=true; a.src=pick;
  document.getElementById('ha').appendChild(a);
  d.textContent='candidates: '+files.join(', ')+'\\nchose: '+pick;
  a.addEventListener('error',function(){
    d.textContent+='\\nAUDIO ERROR code='+(a.error&&a.error.code); });
  var p=a.play();
  if(p&&p.then){ p.then(function(){ d.textContent+='\\nplay() resolved — autoplay allowed'; })
                  .catch(function(e){ d.textContent+='\\nplay() rejected: '+e.name+' — '+e.message; }); }
  else { d.textContent+='\\nplay() returned no promise'; }
})();
</script>
</div>`,
      afmt: `<div class="card"><b>{{BirdName}}</b><br><i>{{SciName}}</i></div>`,
    },
  ],
};

// ?noproto=1 leaves out the prototype-only note type, so the file can be
// compared byte-for-byte against a genanki build of the same catalog.
const NO_PROTO = new URLSearchParams(location.search).has('noproto');

async function fetchBytes(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function buildRealDeck() {
  const t0 = performance.now();
  const models = await (await fetch('model.generated.json')).json();
  const manifest = await (await fetch('catalog/manifest.json')).json();
  log(`note types from avianki.anki_model: ${models.map((m) => `${m.name} (${m.id})`).join(', ')}`);
  log(`deck id from seed "${DECK_SEED}": ${DECK_ID}`);

  const media = new Map();
  const notes = [];
  let bytes = 0;

  for (const sp of manifest) {
    log(`fetching ${sp.name}…`);
    for (const im of sp.images.concat(sp.audio)) {
      const b = await fetchBytes('catalog/' + im.file);
      media.set(im.file, b);
      bytes += b.length;
    }
    const img = (i) => (sp.images[i] ? `<img src="${sp.images[i].file}">` : '');
    const snd = (i) => (sp.audio[i] ? `[sound:${sp.audio[i].file}]` : '');
    const credits = sp.images.concat(sp.audio)
      .map((m) => m.licence ?? m.attribution).join(' · ');
    const desc = `A ${sp.name} is a bird. ${credits}`;
    const fields = [sp.name, sp.sciName, img(0), img(1), snd(0), snd(1),
                    desc, desc.replaceAll(sp.name, '<em>[redacted]</em>')];

    // Same guid recipe as cli.py: guid_for(deck_seed, name, "v1_photo")
    notes.push({ modelId: models[0].id, fields,
                 guid: await guidFor(DECK_SEED, sp.name, 'v1_photo') });
    notes.push({ modelId: models[1].id, fields,
                 guid: await guidFor(DECK_SEED, sp.name, 'v1_desc') });

    // …and one note on the prototype randomiser type, with up to 3 clips.
    if (!NO_PROTO) {
      const f = (i) => (sp.audio[i] ? sp.audio[i].file : '');
      notes.push({
        modelId: RANDOM_AUDIO_MODEL.id,
        fields: [sp.name, sp.sciName, snd(0), snd(1), snd(2), f(0), f(1), f(2)],
        guid: await guidFor(DECK_SEED, sp.name, 'proto_random_audio'),
      });
    }
  }

  log(`fetched ${media.size} media files, ${mb(bytes)}`);
  const blob = await buildApkg({
    deckId: DECK_ID, deckName: DECK_NAME,
    models: NO_PROTO ? models : [...models, RANDOM_AUDIO_MODEL],
    notes, media, timestamp: TIMESTAMP,
    onProgress: (s) => log('  ' + s),
  });
  log(`built ${mb(blob.size)} in ${((performance.now() - t0) / 1000).toFixed(1)}s${heap()}`);
  download(blob, NO_PROTO ? 'AviAnki-browser-noproto.apkg' : 'AviAnki-browser-built.apkg');
}

// --- scale test -----------------------------------------------------------
// Synthetic media at the sizes the research measured: images ~135 MB / 1000
// species across 3 images, audio ~117 KB per clip.
async function scaleTest(species) {
  const t0 = performance.now();
  const models = await (await fetch('model.generated.json')).json();
  const seed = await fetchBytes('catalog/american-robin_img1.jpg');
  const audioSeed = await fetchBytes('catalog/american-robin_audio1.mp3');

  const media = new Map();
  const notes = [];
  let bytes = 0;
  for (let i = 0; i < species; i++) {
    const name = `Species ${i}`;
    for (let k = 0; k < 3; k++) {
      // distinct bytes per file so nothing is deduped by accident
      const b = seed.slice();
      b[0] = i & 0xff; b[1] = k;
      media.set(`s${i}_img${k}.jpg`, b); bytes += b.length;
    }
    const a = audioSeed.slice(); a[0] = i & 0xff;
    media.set(`s${i}_a.mp3`, a); bytes += a.length;
    const fields = [name, `Genus sp${i}`, `<img src="s${i}_img0.jpg">`,
                    `<img src="s${i}_img1.jpg">`, `[sound:s${i}_a.mp3]`, '',
                    'A description.', 'A description.'];
    notes.push({ modelId: models[0].id, fields, guid: await guidFor(DECK_SEED, name, 'v1_photo') });
    notes.push({ modelId: models[1].id, fields, guid: await guidFor(DECK_SEED, name, 'v1_desc') });
    if (i % 100 === 0) log(`  prepared ${i}/${species}${heap()}`);
  }
  log(`synthetic corpus: ${media.size} files, ${mb(bytes)}${heap()}`);

  const tBuild = performance.now();
  const blob = await buildApkg({
    deckId: DECK_ID, deckName: DECK_NAME, models, notes, media,
    timestamp: TIMESTAMP,
    onProgress: (s) => { if (s.endsWith('0%') || !s.startsWith('zipping ')) log('  ' + s + heap()); },
  });
  log(`SCALE ${species} species: ${notes.length} notes, ${media.size} media, ` +
      `${mb(blob.size)} apkg`);
  log(`  prepare ${((tBuild - t0) / 1000).toFixed(1)}s, ` +
      `build ${((performance.now() - tBuild) / 1000).toFixed(1)}s, ` +
      `total ${((performance.now() - t0) / 1000).toFixed(1)}s${heap()}`);
  if ($('scaleDownload').checked) download(blob, `scale-${species}.apkg`);
  else log('  (download skipped — tick the box to save it)');
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  log(`→ downloaded ${filename} (${mb(blob.size)})`);
}

$('build').onclick = () => buildRealDeck().catch((e) => log('ERROR ' + e.stack));
$('scale').onclick = () =>
  scaleTest(parseInt($('speciesCount').value, 10)).catch((e) => log('ERROR ' + e.stack));
log(`ready — ${navigator.userAgent}`);
log(`crypto.subtle: ${!!crypto.subtle}, performance.memory: ${!!performance.memory}`);
