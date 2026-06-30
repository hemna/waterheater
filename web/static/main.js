const socket = io('/control');

let timerCountdownInterval = null;
let currentTimerEnd = null;
let currentResetTemp = 108;

let startTimerCountdownInterval = null;
let currentStartTimerEnd = null;
let currentIntermediateTemp = null;
let currentResetDuration = null;

// Heater duration tracking
let heaterOnSince = null;  // Unix timestamp (seconds) or null
let heaterDurationInterval = null;

// Chart state
let currentChartPeriod = 'day';

function formatCountdown(secondsLeft) {
    if (secondsLeft <= 0) return '0:00';
    const m = Math.floor(secondsLeft / 60);
    const s = Math.floor(secondsLeft % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
}

function formatDuration(seconds) {
    if (seconds < 0) seconds = 0;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) {
        return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }
    return m + ':' + (s < 10 ? '0' : '') + s;
}

function updateHeaterDurationDisplay() {
    var el = document.getElementById('heaterDuration');
    if (!el) return;
    if (!heaterOnSince) {
        el.hidden = true;
        if (heaterDurationInterval) {
            clearInterval(heaterDurationInterval);
            heaterDurationInterval = null;
        }
        return;
    }
    el.hidden = false;
    function tick() {
        if (!heaterOnSince) {
            el.hidden = true;
            return;
        }
        var now = Date.now() / 1000;
        var elapsed = Math.max(0, now - heaterOnSince);
        el.textContent = 'Burner on for ' + formatDuration(elapsed);
    }
    tick();
    if (!heaterDurationInterval) {
        heaterDurationInterval = setInterval(tick, 1000);
    }
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

let ldrTimerCountdownInterval = null;
let currentLdrTimerEnd = null;

let offTimerCountdownInterval = null;
let currentOffTimerEnd = null;

function updateOffTimerDisplay(endTimestamp) {
    currentOffTimerEnd = endTimestamp || null;
    const el = document.getElementById('offTimerCountdown');
    if (!el) return;
    if (!currentOffTimerEnd) {
        el.hidden = true;
        if (offTimerCountdownInterval) {
            clearInterval(offTimerCountdownInterval);
            offTimerCountdownInterval = null;
        }
        return;
    }
    el.hidden = false;
    function tick() {
        if (!currentOffTimerEnd) return;
        const now = Date.now() / 1000;
        const left = Math.max(0, currentOffTimerEnd - now);
        el.textContent = 'Resetting to 108°F in ' + formatCountdown(left);
        if (left <= 0 && offTimerCountdownInterval) {
            clearInterval(offTimerCountdownInterval);
            offTimerCountdownInterval = null;
        }
    }
    tick();
    if (!offTimerCountdownInterval) {
        offTimerCountdownInterval = setInterval(tick, 1000);
    }
}

function updateLdrTimerDisplay(endTimestamp) {
    currentLdrTimerEnd = endTimestamp || null;
    const el = document.getElementById('ldrTimerCountdown');
    if (!el) return;
    if (!currentLdrTimerEnd) {
        el.hidden = true;
        if (ldrTimerCountdownInterval) {
            clearInterval(ldrTimerCountdownInterval);
            ldrTimerCountdownInterval = null;
        }
        return;
    }
    el.hidden = false;
    function tick() {
        if (!currentLdrTimerEnd) return;
        const now = Date.now() / 1000;
        const left = Math.max(0, currentLdrTimerEnd - now);
        el.textContent = 'Reducing to 97°F in ' + formatCountdown(left);
        if (left <= 0 && ldrTimerCountdownInterval) {
            clearInterval(ldrTimerCountdownInterval);
            ldrTimerCountdownInterval = null;
        }
    }
    tick();
    if (!ldrTimerCountdownInterval) {
        ldrTimerCountdownInterval = setInterval(tick, 1000);
    }
}


socket.on('ldr_timer_state', function(msg) {
    updateLdrTimerDisplay(msg.end_timestamp || null);
});

socket.on('off_timer_state', function(msg) {
    updateOffTimerDisplay(msg.end_timestamp || null);
});

// ── Heater History ────────────────────────────────────────────────────
socket.on('heater_history', function(msg) {
    var container = document.getElementById('historyList');
    var statsEl = document.getElementById('historyStats');
    if (!container) return;

    // Render stats
    if (statsEl && msg.stats) {
        var s = msg.stats;
        statsEl.textContent = 'Today: ' + s.today_events + ' events · Avg: ' + formatDuration(s.avg_duration) + ' · Longest: ' + formatDuration(s.max_duration);
    }

    // Render events
    if (!msg.events || msg.events.length === 0) {
        container.innerHTML = '<p class="history-empty">No heating events recorded yet.</p>';
        return;
    }

    var html = '';
    msg.events.forEach(function(ev) {
        var start = new Date(ev.start * 1000);
        var timeStr = start.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        var dateStr = start.toLocaleDateString([], {month: 'short', day: 'numeric'});
        var durStr = ev.duration != null ? formatDuration(ev.duration) : 'ongoing…';
        var cls = ev.duration == null ? 'history-item history-item--active' : 'history-item';
        html += '<div class="' + cls + '">';
        html += '<span class="history-time">' + dateStr + ' ' + timeStr + '</span>';
        html += '<span class="history-dur">' + durStr + '</span>';
        html += '</div>';
    });
    container.innerHTML = html;

    // Refresh chart when history updates
    if (typeof currentChartPeriod !== 'undefined') {
        socket.emit('get_chart_data', { period: currentChartPeriod });
    }
});

// ── Usage Chart data handler ──────────────────────────────────────────
socket.on('chart_data', function(msg) {
    var canvas = document.getElementById('usageChart');
    if (!canvas) return;
    // Chart instance is stored on the canvas by Chart.js
    var chartInstance = Chart.getChart(canvas);
    if (!chartInstance) return;
    chartInstance.data.labels = msg.data.labels;
    chartInstance.data.datasets[0].data = msg.data.values;
    chartInstance.update();
});

function setConnStatus(state) {
    // state: 'connected' | 'disconnected' | 'reconnecting'
    var el = document.getElementById('connStatus');
    var label = el.querySelector('.conn-label');
    el.className = 'conn-status conn-status--' + state;
    label.textContent = state.charAt(0).toUpperCase() + state.slice(1);
}

socket.on('connect', function() {
    console.log('Connected to server');
    setConnStatus('connected');
});

socket.on('disconnect', function() {
    console.log('Disconnected from server');
    setConnStatus('disconnected');
});

socket.on('reconnecting', function() {
    console.log('Reconnecting...');
    setConnStatus('reconnecting');
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

// ── LDR heater detection ──────────────────────────────────────────────
socket.on('heater_state', function(msg) {
    var on = msg.on;
    var indicator = document.getElementById('heaterIndicator');
    var label = document.getElementById('heaterLabel');
    var checkbox = document.getElementById('ldrAutoTimer');

    if (on) {
        indicator.classList.remove('heater-indicator--off');
        indicator.classList.add('heater-indicator--on');
        label.textContent = 'Heater ON';
        label.classList.add('heater-label--on');
    } else {
        indicator.classList.remove('heater-indicator--on');
        indicator.classList.add('heater-indicator--off');
        label.textContent = 'Heater OFF';
        label.classList.remove('heater-label--on');
    }

    // Update heater duration tracking
    heaterOnSince = msg.on_since || null;
    updateHeaterDurationDisplay();

    if (checkbox) {
        checkbox.checked = msg.auto_timer_enabled;
    }

    var progressiveCheckbox = document.getElementById('ldrProgressive');
    if (progressiveCheckbox) {
        progressiveCheckbox.checked = msg.progressive_enabled;
    }

    // Sync floor temperature from server
    var floorInput = document.getElementById('progressiveFloor');
    if (floorInput && msg.progressive_min_temp != null) {
        floorInput.value = msg.progressive_min_temp;
    }

    // Update progressive cooling active state
    var progressiveBtn = document.getElementById('startProgressiveNow');
    var progressiveStatus = document.getElementById('progressiveStatus');
    if (progressiveBtn) {
        if (msg.progressive_active) {
            progressiveBtn.textContent = 'Stop progressive cooling';
            progressiveBtn.classList.add('btn-progressive-now--active');
        } else {
            progressiveBtn.textContent = 'Start progressive cooling now';
            progressiveBtn.classList.remove('btn-progressive-now--active');
        }
    }
    if (progressiveStatus) {
        if (msg.progressive_active) {
            progressiveStatus.textContent = 'Progressive cooling active — dropping −1°F/min';
            progressiveStatus.hidden = false;
        } else {
            progressiveStatus.hidden = true;
        }
    }
});

// LDR checkbox listeners — must wait for DOM to be ready
document.addEventListener('DOMContentLoaded', function() {
    var ldrCheckbox = document.getElementById('ldrAutoTimer');
    if (ldrCheckbox) {
        ldrCheckbox.addEventListener('change', function() {
            socket.emit('set_ldr_auto_timer', {'enabled': this.checked});
        });
    }

    var ldrProgressiveCheckbox = document.getElementById('ldrProgressive');
    if (ldrProgressiveCheckbox) {
        ldrProgressiveCheckbox.addEventListener('change', function() {
            socket.emit('set_ldr_progressive', {'enabled': this.checked});
        });
    }

    var progressiveNowBtn = document.getElementById('startProgressiveNow');
    if (progressiveNowBtn) {
        progressiveNowBtn.addEventListener('click', function() {
            if (this.classList.contains('btn-progressive-now--active')) {
                socket.emit('stop_progressive_now', {});
            } else {
                socket.emit('start_progressive_now', {});
            }
        });
    }

    var setFloorBtn = document.getElementById('setProgressiveFloor');
    if (setFloorBtn) {
        setFloorBtn.addEventListener('click', function() {
            var temp = parseInt(document.getElementById('progressiveFloor').value, 10) || 80;
            socket.emit('set_progressive_floor', {'temperature': temp});
        });
    }

    // ── Usage Chart ───────────────────────────────────────────────────────
    var usageChart = null;

    function initChart() {
        var ctx = document.getElementById('usageChart');
        if (!ctx) return;
        usageChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Heating (min)',
                    data: [],
                    backgroundColor: 'rgba(239, 108, 0, 0.6)',
                    borderColor: 'rgba(239, 108, 0, 1)',
                    borderWidth: 1,
                    borderRadius: 3,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                var val = context.parsed.y;
                                if (val >= 60) {
                                    var h = Math.floor(val / 60);
                                    var m = Math.round(val % 60);
                                    return h + 'h ' + m + 'm';
                                }
                                return Math.round(val) + ' min';
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Minutes' },
                        grid: { color: 'rgba(255,255,255,0.06)' },
                        ticks: { color: '#aaa' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#aaa', maxRotation: 0 }
                    }
                }
            }
        });
        // Request initial data
        socket.emit('get_chart_data', { period: currentChartPeriod });
    }

    function setChartPeriod(period) {
        currentChartPeriod = period;
        document.querySelectorAll('.btn-chart-toggle').forEach(function(btn) {
            btn.classList.remove('active');
        });
        var id = 'chart' + period.charAt(0).toUpperCase() + period.slice(1);
        var activeBtn = document.getElementById(id);
        if (activeBtn) activeBtn.classList.add('active');
        socket.emit('get_chart_data', { period: period });
    }

    var chartDayBtn = document.getElementById('chartDay');
    var chartMonthBtn = document.getElementById('chartMonth');
    var chartYearBtn = document.getElementById('chartYear');
    if (chartDayBtn) chartDayBtn.addEventListener('click', function() { setChartPeriod('day'); });
    if (chartMonthBtn) chartMonthBtn.addEventListener('click', function() { setChartPeriod('month'); });
    if (chartYearBtn) chartYearBtn.addEventListener('click', function() { setChartPeriod('year'); });

    initChart();
});
