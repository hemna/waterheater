const socket = io('/control');

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
    $('#currentTemperature').val(msg.temperature);
});
