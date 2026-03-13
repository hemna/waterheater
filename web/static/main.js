const socket = io('/control');

let timerCountdownInterval = null;
let currentTimerEnd = null;
let currentResetTemp = 108;

let startTimerCountdownInterval = null;
let currentStartTimerEnd = null;
let currentIntermediateTemp = null;
let currentResetDuration = null;

function formatCountdown(secondsLeft) {
    if (secondsLeft <= 0) return '0:00';
    const m = Math.floor(secondsLeft / 60);
    const s = Math.floor(secondsLeft % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
}

function updateTimerDisplay(endTimestamp, resetTemperature) {
    currentTimerEnd = endTimestamp || null;
    if (resetTemperature != null) currentResetTemp = resetTemperature;
    const el = document.getElementById('timerCountdown');
    if (!currentTimerEnd) {
        el.hidden = true;
        if (timerCountdownInterval) {
            clearInterval(timerCountdownInterval);
            timerCountdownInterval = null;
        }
        return;
    }
    el.hidden = false;
    function tick() {
        if (!currentTimerEnd) return;
        const now = Date.now() / 1000;
        const left = Math.max(0, currentTimerEnd - now);
        el.textContent = 'Resetting to ' + currentResetTemp + '°F in ' + formatCountdown(left);
        if (left <= 0 && timerCountdownInterval) {
            clearInterval(timerCountdownInterval);
            timerCountdownInterval = null;
        }
    }
    tick();
    if (!timerCountdownInterval) {
        timerCountdownInterval = setInterval(tick, 1000);
    }
}

function updateStartTimerDisplay(endTimestamp, intermediateTemp, resetDuration) {
    currentStartTimerEnd = endTimestamp || null;
    if (intermediateTemp != null) currentIntermediateTemp = intermediateTemp;
    if (resetDuration != null) currentResetDuration = resetDuration;
    const el = document.getElementById('startTimerCountdown');
    if (!currentStartTimerEnd) {
        el.hidden = true;
        if (startTimerCountdownInterval) {
            clearInterval(startTimerCountdownInterval);
            startTimerCountdownInterval = null;
        }
        return;
    }
    el.hidden = false;
    function tick() {
        if (!currentStartTimerEnd) return;
        const now = Date.now() / 1000;
        const left = Math.max(0, currentStartTimerEnd - now);
        el.textContent = 'Reducing to ' + currentIntermediateTemp + '°F in ' + formatCountdown(left) + ' (then ' + currentResetDuration + ' min reset)';
        if (left <= 0 && startTimerCountdownInterval) {
            clearInterval(startTimerCountdownInterval);
            startTimerCountdownInterval = null;
        }
    }
    tick();
    if (!startTimerCountdownInterval) {
        startTimerCountdownInterval = setInterval(tick, 1000);
    }
}

socket.on('connect', function() {
    console.log('Connected to server');
});

socket.on('motor_status', function(msg) {
    console.log("Motor status", msg);
    document.getElementById('result').innerText = msg.message;
});

socket.on('temperature_status', function(msg) {
    console.log("Temperature status", msg);
    document.getElementById('result').innerText = msg.message;
});

socket.on('temperature_update', function(msg) {
    console.log("Temperature updated", msg);
    var t = msg.temperature;
    $('#currentTemperature').val(t);
    $('#tempDisplay').text(t);
});

socket.on('timer_state', function(msg) {
    updateTimerDisplay(msg.end_timestamp || null, msg.reset_temperature);
});

socket.on('start_timer_state', function(msg) {
    updateStartTimerDisplay(msg.end_timestamp || null, msg.intermediate_temperature, msg.reset_duration);
});
