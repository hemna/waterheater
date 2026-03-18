# basic-components UI Rewrite Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the waterheater web UI using basic-components (JinjaX), Tailwind CSS, and Alpine.js while keeping Flask-SocketIO for real-time communication.

**Architecture:** Server-rendered JinjaX components styled with Tailwind CSS. Alpine.js replaces jQuery for client-side reactivity and state management. Socket.IO remains the real-time transport. Alpine.js global store holds temperature/timer state, Socket.IO events update the store, and Alpine's reactivity auto-renders the UI.

**Tech Stack:**
- basic-components (JinjaX component library) + Tailwind CSS
- Alpine.js (client-side reactivity, replaces jQuery)
- Flask-SocketIO (unchanged)
- Node.js (dev only, for Tailwind CSS compilation on Mac)

**Branch:** `experimental/basic-components` (off `master`)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `pyproject.toml` | Modify | Add `jinjax`, `basic-components[utils]` |
| `main.py` | Modify | Add JinjaX catalog setup, update Flask template rendering |
| `web/templates/index.html` | Rewrite | JinjaX components + Alpine.js store + Socket.IO |
| `web/static/main.js` | Rewrite | Alpine.js store + Socket.IO integration (~40 lines) |
| `web/static/main.css` | Delete | Replaced by Tailwind output |
| `web/static/src/input.css` | Create | Tailwind base imports |
| `web/static/dist/output.css` | Create (generated) | Compiled Tailwind CSS |
| `web/components/ui/` | Create (via CLI) | basic-components JinjaX files |
| `package.json` | Create | Tailwind dev dependencies |
| `tailwind.config.js` | Create | Tailwind config scanning templates + components |
| `.gitignore` | Modify | Add `node_modules/` |

---

## Chunk 1: Infrastructure Setup

### Task 1: Create experimental branch + install dependencies

**Files:**
- Create: `package.json`
- Create: `tailwind.config.js`
- Create: `web/static/src/input.css`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1.1: Create and checkout experimental branch**

```bash
git checkout -b experimental/basic-components master
```

- [ ] **Step 1.2: Add Python dependencies to pyproject.toml**

Add to dependencies array in `pyproject.toml`:
```toml
    "jinjax>=0.47",
    "basic-components[utils]>=0.1.0",
```

- [ ] **Step 1.3: Create package.json for Tailwind**

Create `package.json`:
```json
{
  "name": "waterheater-ui",
  "version": "1.0.0",
  "scripts": {
    "build": "npx tailwindcss -i ./web/static/src/input.css -o ./web/static/dist/output.css",
    "build-prod": "npx tailwindcss -i ./web/static/src/input.css -o ./web/static/dist/output.css --minify",
    "watch": "npx tailwindcss -i ./web/static/src/input.css -o ./web/static/dist/output.css --watch"
  },
  "devDependencies": {
    "@tailwindcss/forms": "^0.5.7",
    "tailwind-merge": "^2.5.3",
    "tailwindcss": "^3.4.10",
    "tailwindcss-animate": "^1.0.7"
  }
}
```

- [ ] **Step 1.4: Create tailwind.config.js**

Create `tailwind.config.js`:
```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './web/templates/**/*.html',
    './web/components/**/*.jinja',
  ],
  theme: {
    extend: {},
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('tailwindcss-animate'),
  ],
}
```

- [ ] **Step 1.5: Create Tailwind input CSS**

Create `web/static/src/input.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 1.6: Create dist directory**

```bash
mkdir -p web/static/dist
```

- [ ] **Step 1.7: Update .gitignore**

Add to `.gitignore`:
```
node_modules/
```

- [ ] **Step 1.8: Install Node dependencies**

```bash
npm install
```

- [ ] **Step 1.9: Build Tailwind CSS (verify setup)**

```bash
npm run build
```

Expected: Creates `web/static/dist/output.css`

- [ ] **Step 1.10: Install Python dependencies**

```bash
uv sync
```

- [ ] **Step 1.11: Commit infrastructure setup**

```bash
git add -A
git commit -m "feat: add basic-components infrastructure (Tailwind, JinjaX deps)"
```

---

### Task 2: Set up JinjaX catalog in Flask

**Files:**
- Modify: `main.py`

- [ ] **Step 2.1: Add JinjaX imports to main.py**

Add near top of `main.py` after existing imports:
```python
import jinjax
from basic_components.utils.jinjax import setup_component_catalog
from basic_components.utils.tailwind import tw
```

- [ ] **Step 2.2: Create JinjaX catalog after Flask app initialization**

After the `flask_app = Flask(...)` block (around line 251), add:
```python
# --- JinjaX Setup ---
jinjax_ext = jinjax.JinjaX(flask_app)
catalog = jinjax_ext.catalog
catalog.add_folder("web/components")
setup_component_catalog(catalog)
flask_app.jinja_env.globals["cn"] = tw
```

- [ ] **Step 2.3: Verify Flask still starts**

```bash
python -c "from main import flask_app; print('Flask app created successfully')"
```

Expected: "Flask app created successfully" (motor code will fail on Mac but Flask setup should work)

- [ ] **Step 2.4: Commit JinjaX setup**

```bash
git add main.py
git commit -m "feat: integrate JinjaX catalog with Flask app"
```

---

### Task 3: Add basic-components UI components

**Files:**
- Create: `web/components/ui/*.jinja` (multiple files)

- [ ] **Step 3.1: Create components directory**

```bash
mkdir -p web/components/ui
```

- [ ] **Step 3.2: Add UI components via CLI**

```bash
uvx --from basic-components components add button card checkbox input label select badge
```

This copies the component `.jinja` files into the current directory structure.

- [ ] **Step 3.3: Move components to correct location if needed**

If components are placed in `./components/ui/`, move them:
```bash
mv components/ui/* web/components/ui/ 2>/dev/null || true
rmdir components/ui components 2>/dev/null || true
```

- [ ] **Step 3.4: Verify components exist**

```bash
ls -la web/components/ui/
```

Expected: Multiple `.jinja` files (Button.jinja, Card.jinja, etc.)

- [ ] **Step 3.5: Commit components**

```bash
git add web/components/
git commit -m "feat: add basic-components UI components (Button, Card, Input, etc.)"
```

---

## Chunk 2: Client-Side Rewrite

### Task 4: Rewrite Alpine.js store + Socket.IO integration

**Files:**
- Rewrite: `web/static/main.js`

- [ ] **Step 4.1: Rewrite main.js with Alpine.js store**

Replace entire contents of `web/static/main.js` with:

```javascript
// Alpine.js global store for waterheater state
document.addEventListener('alpine:init', () => {
    Alpine.store('heater', {
        // State
        temperature: 108,
        timerEnd: null,
        resetTemp: 108,
        startTimerEnd: null,
        intermediateTemp: null,
        resetDuration: null,
        statusMessage: '',

        // Computed-like methods
        timerCountdown() {
            if (!this.timerEnd) return null;
            const left = Math.max(0, this.timerEnd - Date.now() / 1000);
            if (left <= 0) return '0:00';
            const m = Math.floor(left / 60);
            const s = Math.floor(left % 60);
            return m + ':' + (s < 10 ? '0' : '') + s;
        },

        startTimerCountdown() {
            if (!this.startTimerEnd) return null;
            const left = Math.max(0, this.startTimerEnd - Date.now() / 1000);
            if (left <= 0) return '0:00';
            const m = Math.floor(left / 60);
            const s = Math.floor(left % 60);
            return m + ':' + (s < 10 ? '0' : '') + s;
        },

        // Actions (emit to Socket.IO)
        increaseTemp() {
            socket.emit('change_temperature', { temperature: 1 });
            this.maybeAutoStartTimer();
        },

        decreaseTemp() {
            socket.emit('change_temperature', { temperature: -1 });
            this.maybeAutoStartTimer();
        },

        setPreset(temp) {
            socket.emit('set_temperature', { temperature: temp });
            this.maybeAutoStartTimer();
        },

        syncReading(temp) {
            socket.emit('set_temperature_reading', { temperature: temp });
        },

        startResetTimer(minutes) {
            socket.emit('set_timer', { duration_minutes: minutes });
        },

        forceReset() {
            socket.emit('force_reset', {});
        },

        startStartTimer(duration, intermediateTemp, resetDuration) {
            socket.emit('set_start_timer', {
                duration_minutes: duration,
                intermediate_temperature: intermediateTemp,
                reset_duration_minutes: resetDuration
            });
        },

        cancelStartTimer() {
            socket.emit('cancel_start_timer', {});
        },

        maybeAutoStartTimer() {
            if (localStorage.getItem('waterheater.autoStartTimer') === 'true') {
                const duration = parseInt(localStorage.getItem('waterheater.timerDuration') || '15', 10);
                socket.emit('set_timer', { duration_minutes: duration });
            }
        }
    });
});

// Socket.IO connection
const socket = io('/control');

socket.on('connect', () => {
    console.log('Connected to server');
    Alpine.store('heater').statusMessage = 'Connected';
});

socket.on('motor_status', (msg) => {
    console.log('Motor status', msg);
    Alpine.store('heater').statusMessage = msg.message;
});

socket.on('temperature_status', (msg) => {
    console.log('Temperature status', msg);
    Alpine.store('heater').statusMessage = msg.message;
});

socket.on('temperature_update', (msg) => {
    console.log('Temperature updated', msg);
    Alpine.store('heater').temperature = msg.temperature;
});

socket.on('timer_state', (msg) => {
    const store = Alpine.store('heater');
    store.timerEnd = msg.end_timestamp || null;
    if (msg.reset_temperature != null) {
        store.resetTemp = msg.reset_temperature;
    }
});

socket.on('start_timer_state', (msg) => {
    const store = Alpine.store('heater');
    store.startTimerEnd = msg.end_timestamp || null;
    if (msg.intermediate_temperature != null) {
        store.intermediateTemp = msg.intermediate_temperature;
    }
    if (msg.reset_duration != null) {
        store.resetDuration = msg.reset_duration;
    }
});

// Countdown tick (updates every second for display)
setInterval(() => {
    // Force Alpine to re-evaluate countdown displays
    Alpine.store('heater').temperature = Alpine.store('heater').temperature;
}, 1000);
```

- [ ] **Step 4.2: Commit Alpine.js store**

```bash
git add web/static/main.js
git commit -m "feat: rewrite main.js as Alpine.js store with Socket.IO integration"
```

---

## Chunk 3: Template Rewrite

### Task 5: Rewrite the template - Temperature card

**Files:**
- Rewrite: `web/templates/index.html` (partial - head + temperature card)

- [ ] **Step 5.1: Rewrite index.html - head and temperature section**

Replace entire contents of `web/templates/index.html` with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Water Heater Control</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <!-- Tailwind compiled CSS -->
    <link href="/static/dist/output.css" rel="stylesheet">
    <!-- Alpine.js -->
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js"></script>
    <!-- Socket.IO -->
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <!-- App JS (Alpine store + Socket.IO) -->
    <script src="/static/main.js"></script>
</head>
<body class="min-h-screen bg-zinc-50 font-[Inter]" x-data x-init="
    // Restore localStorage preferences
    $store.heater.temperature = parseInt('{{ initial_temperature|default(108) }}', 10);
">
    <div class="max-w-md mx-auto p-6 space-y-5">
        <!-- Header -->
        <header class="text-center mb-8">
            <h1 class="text-2xl font-bold text-zinc-900 tracking-tight">Water Heater</h1>
            <p class="text-sm text-zinc-500">Temperature & timer control</p>
        </header>

        <!-- Temperature Card -->
        <Card>
            <CardHeader>
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Temperature</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <!-- Temperature Display -->
                <div class="flex items-baseline justify-center gap-1">
                    <span class="text-6xl font-bold tracking-tight text-zinc-900" x-text="$store.heater.temperature">108</span>
                    <span class="text-2xl font-medium text-zinc-400">°F</span>
                </div>

                <!-- +/- Controls -->
                <div class="flex justify-center gap-4">
                    <Button 
                        variant="outline" 
                        size="icon"
                        className="w-14 h-14 rounded-full text-2xl"
                        @click="$store.heater.decreaseTemp()"
                    >−</Button>
                    <Button 
                        variant="outline" 
                        size="icon"
                        className="w-14 h-14 rounded-full text-2xl"
                        @click="$store.heater.increaseTemp()"
                    >+</Button>
                </div>

                <!-- Sync Reading -->
                <div class="flex items-center gap-2">
                    <Input 
                        type="number" 
                        x-model="$store.heater.temperature"
                        min="90" 
                        max="130"
                        className="w-20 text-center"
                    />
                    <Button 
                        variant="outline" 
                        size="sm"
                        @click="$store.heater.syncReading($store.heater.temperature)"
                    >Sync reading</Button>
                </div>

                <!-- Preset Buttons -->
                <div class="flex gap-2">
                    <Button variant="outline" className="flex-1" @click="$store.heater.setPreset(97)">97°F</Button>
                    <Button variant="outline" className="flex-1 text-orange-600 border-orange-300 hover:bg-orange-50" @click="$store.heater.setPreset(108)">108°F</Button>
                    <Button variant="outline" className="flex-1 text-orange-600 border-orange-300 hover:bg-orange-50" @click="$store.heater.setPreset(110)">110°F</Button>
                    <Button variant="outline" className="flex-1 text-orange-600 border-orange-300 hover:bg-orange-50" @click="$store.heater.setPreset(120)">120°F</Button>
                </div>

                <!-- Auto-start Timer Checkbox -->
                <div class="space-y-1" x-data="{ autoStart: localStorage.getItem('waterheater.autoStartTimer') === 'true' }">
                    <div class="flex items-center gap-2">
                        <Checkbox 
                            id="autoStartTimer"
                            x-model="autoStart"
                            @change="localStorage.setItem('waterheater.autoStartTimer', autoStart ? 'true' : 'false')"
                        />
                        <Label htmlFor="autoStartTimer" className="text-sm">Auto-start timer when temperature is set</Label>
                    </div>
                    <p class="text-xs text-zinc-500 ml-6">If a timer is already running, it will be reset.</p>
                </div>
            </CardContent>
        </Card>

        <!-- Start Timer Card (Task 6) -->
        <!-- Reset Timer Card (Task 7) -->
        <!-- Status Message (Task 7) -->

    </div>
</body>
</html>
```

- [ ] **Step 5.2: Rebuild Tailwind CSS**

```bash
npm run build
```

- [ ] **Step 5.3: Commit temperature card**

```bash
git add web/templates/index.html web/static/dist/output.css
git commit -m "feat: rewrite temperature card with JinjaX + Alpine.js"
```

---

### Task 6: Rewrite the template - Start timer card

**Files:**
- Modify: `web/templates/index.html`

- [ ] **Step 6.1: Add Start Timer card after Temperature card**

Replace the `<!-- Start Timer Card (Task 6) -->` comment with:

```html
        <!-- Start Timer Card -->
        <Card x-data="{
            duration: localStorage.getItem('waterheater.startTimerDuration') || '15',
            intermediateTemp: localStorage.getItem('waterheater.startTimerIntermediateTemp') || '106',
            resetDuration: localStorage.getItem('waterheater.startTimerResetDuration') || '30'
        }">
            <CardHeader>
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Start Timer</CardTitle>
                <CardDescription>Reduce temperature after a set time, then trigger reset timer.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
                <!-- Duration + Intermediate Temp -->
                <div class="flex items-center gap-2 flex-wrap">
                    <select 
                        x-model="duration"
                        @change="localStorage.setItem('waterheater.startTimerDuration', duration)"
                        class="rounded-md border border-zinc-200 px-3 py-2 text-sm"
                    >
                        <option value="1">1 min</option>
                        <option value="5">5 min</option>
                        <option value="15">15 min</option>
                        <option value="30">30 min</option>
                        <option value="60">1 hr</option>
                        <option value="120">2 hr</option>
                    </select>
                    <span class="text-sm text-zinc-500">then reduce to</span>
                    <Input 
                        type="number" 
                        x-model="intermediateTemp"
                        @change="localStorage.setItem('waterheater.startTimerIntermediateTemp', intermediateTemp)"
                        min="90" 
                        max="130"
                        className="w-16 text-center"
                    />
                    <span class="text-sm text-zinc-500">°F</span>
                </div>

                <!-- Reset Duration -->
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-sm text-zinc-500">then reset timer for</span>
                    <select 
                        x-model="resetDuration"
                        @change="localStorage.setItem('waterheater.startTimerResetDuration', resetDuration)"
                        class="rounded-md border border-zinc-200 px-3 py-2 text-sm"
                    >
                        <option value="1">1 min</option>
                        <option value="5">5 min</option>
                        <option value="15">15 min</option>
                        <option value="30">30 min</option>
                        <option value="60">1 hr</option>
                        <option value="120">2 hr</option>
                    </select>
                    <span class="text-sm text-zinc-500">to 108°F</span>
                </div>

                <!-- Buttons -->
                <div class="flex gap-2">
                    <Button 
                        @click="$store.heater.startStartTimer(parseInt(duration), parseInt(intermediateTemp), parseInt(resetDuration))"
                    >Start timer</Button>
                    <Button 
                        variant="outline"
                        @click="$store.heater.cancelStartTimer()"
                    >Cancel</Button>
                </div>

                <!-- Countdown Display -->
                <div 
                    x-show="$store.heater.startTimerEnd"
                    class="p-3 rounded-md bg-orange-50 border border-orange-200 text-orange-700 text-sm font-medium"
                >
                    Reducing to <span x-text="$store.heater.intermediateTemp"></span>°F in 
                    <span x-text="$store.heater.startTimerCountdown()"></span>
                    (then <span x-text="$store.heater.resetDuration"></span> min reset)
                </div>
            </CardContent>
        </Card>
```

- [ ] **Step 6.2: Rebuild Tailwind CSS**

```bash
npm run build
```

- [ ] **Step 6.3: Commit start timer card**

```bash
git add web/templates/index.html web/static/dist/output.css
git commit -m "feat: add start timer card with JinjaX + Alpine.js"
```

---

### Task 7: Rewrite the template - Reset timer card + status

**Files:**
- Modify: `web/templates/index.html`

- [ ] **Step 7.1: Add Reset Timer card and status message**

Replace the `<!-- Reset Timer Card (Task 7) -->` and `<!-- Status Message (Task 7) -->` comments with:

```html
        <!-- Reset Timer Card -->
        <Card x-data="{ duration: localStorage.getItem('waterheater.timerDuration') || '15' }">
            <CardHeader>
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Reset Timer</CardTitle>
                <CardDescription>Return to 108°F after a set time.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
                <!-- Duration + Start Button -->
                <div class="flex items-center gap-2">
                    <select 
                        x-model="duration"
                        @change="localStorage.setItem('waterheater.timerDuration', duration)"
                        class="rounded-md border border-zinc-200 px-3 py-2 text-sm"
                    >
                        <option value="1">1 min</option>
                        <option value="5">5 min</option>
                        <option value="15">15 min</option>
                        <option value="30">30 min</option>
                        <option value="60">1 hr</option>
                        <option value="120">2 hr</option>
                    </select>
                    <Button @click="$store.heater.startResetTimer(parseInt(duration))">Start timer</Button>
                </div>

                <!-- Countdown Display -->
                <div 
                    x-show="$store.heater.timerEnd"
                    class="p-3 rounded-md bg-orange-50 border border-orange-200 text-orange-700 text-sm font-medium"
                >
                    Resetting to <span x-text="$store.heater.resetTemp"></span>°F in 
                    <span x-text="$store.heater.timerCountdown()"></span>
                </div>

                <!-- Force Reset Button -->
                <Button 
                    variant="ghost"
                    className="text-zinc-500 hover:text-red-600"
                    @click="$store.heater.forceReset()"
                >Force reset to 108°F</Button>
            </CardContent>
        </Card>

        <!-- Status Message -->
        <div 
            x-show="$store.heater.statusMessage"
            x-text="$store.heater.statusMessage"
            class="text-center text-sm text-zinc-500 p-3 bg-white rounded-md border border-zinc-200"
        ></div>
```

- [ ] **Step 7.2: Rebuild Tailwind CSS**

```bash
npm run build
```

- [ ] **Step 7.3: Commit reset timer card**

```bash
git add web/templates/index.html web/static/dist/output.css
git commit -m "feat: add reset timer card and status message"
```

---

## Chunk 4: Cleanup

### Task 8: Delete old CSS + final cleanup

**Files:**
- Delete: `web/static/main.css`
- Modify: `.gitignore`

- [ ] **Step 8.1: Delete old main.css**

```bash
rm web/static/main.css
```

- [ ] **Step 8.2: Final Tailwind production build**

```bash
npm run build-prod
```

- [ ] **Step 8.3: Verify .gitignore has node_modules**

Check `.gitignore` contains `node_modules/` (added in Task 1).

- [ ] **Step 8.4: Commit cleanup**

```bash
git add -A
git commit -m "chore: remove old Bootstrap CSS, finalize build"
```

- [ ] **Step 8.5: Verify branch state**

```bash
git log --oneline -10
git status
```

Expected: Clean working tree, multiple commits on `experimental/basic-components` branch.

---

## Testing

After completing all tasks:

1. **On Mac (without motor):** Run `python main.py` - Flask should start, open browser to `http://localhost:80`
2. **Visual check:** UI should render with Tailwind styling
3. **Functional check:** Temperature buttons should work (Socket.IO), timer countdowns should display
4. **On Pi:** Deploy and test full functionality with motor control

## Rollback

If the experiment doesn't work out:
```bash
git checkout master
git branch -D experimental/basic-components
```

Your master branch remains untouched throughout.
