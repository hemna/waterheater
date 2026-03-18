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
            socket.emit('set_temperature_reading', { temperature: parseInt(temp, 10) });
        },

        startResetTimer(minutes) {
            socket.emit('set_timer', { duration_minutes: parseInt(minutes, 10) });
        },

        forceReset() {
            socket.emit('force_reset', {});
        },

        startStartTimer(duration, intermediateTemp, resetDuration) {
            socket.emit('set_start_timer', {
                duration_minutes: parseInt(duration, 10),
                intermediate_temperature: parseInt(intermediateTemp, 10),
                reset_duration_minutes: parseInt(resetDuration, 10)
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
    // Touch the store to trigger Alpine reactivity for countdown displays
    const store = Alpine.store('heater');
    if (store.timerEnd || store.startTimerEnd) {
        // Force re-render by touching a reactive property
        store.statusMessage = store.statusMessage;
    }
}, 1000);
