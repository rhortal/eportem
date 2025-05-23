// eportem/web_ui/static/app.js

document.addEventListener("DOMContentLoaded", function () {
    // Elements
    const updatesToggle = document.getElementById("updates-toggle");
    const locationToggle = document.getElementById("location-toggle");
    const telegramToggle = document.getElementById("telegram-toggle");
    const slackToggle = document.getElementById("slack-toggle");
    const slackStatusToggle = document.getElementById("slack-status-toggle");
    const scheduleTable = document.getElementById("schedule-table");
    const addRowBtn = document.getElementById("add-row-btn");
    const newTimeInput = document.getElementById("new-time");
    const newActionInput = document.getElementById("new-action");

    // Fetch and render state
    function fetchState() {
        fetch("/api/state")
            .then(res => res.json())
            .then(state => {
                updatesToggle.checked = state.updates_enabled;
                locationToggle.checked = (state.location === "office");
                telegramToggle.checked = state.telegram_enabled;
                slackToggle.checked = state.slack_enabled;
                slackStatusToggle.checked = state.slack_status_enabled;
                renderSchedule(state.schedule);
            });
    }

    // Toggle handlers
    updatesToggle.addEventListener("change", function () {
        updateToggle("updates_enabled", updatesToggle.checked);
    });
    locationToggle.addEventListener("change", function () {
        updateToggle("location", locationToggle.checked ? "office" : "home");
    });
    telegramToggle.addEventListener("change", function () {
        updateToggle("telegram_enabled", telegramToggle.checked);
    });
    slackToggle.addEventListener("change", function () {
        updateToggle("slack_enabled", slackToggle.checked);
    });
    slackStatusToggle.addEventListener("change", function () {
        updateToggle("slack_status_enabled", slackStatusToggle.checked);
    });

    function updateToggle(key, value) {
        fetch("/api/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ key, value })
        }).then(fetchState);
    }

    // Render schedule table
    function renderSchedule(schedule) {
        // Clear table except header
        while (scheduleTable.rows.length > 1) {
            scheduleTable.deleteRow(1);
        }
        schedule.forEach(row => {
            const tr = scheduleTable.insertRow();
            // Time
            const tdTime = tr.insertCell();
            tdTime.textContent = row.time;
            // Action
            const tdAction = tr.insertCell();
            tdAction.textContent = row.action;
            // Enabled toggle
            const tdEnabled = tr.insertCell();
            const enabledToggle = document.createElement("input");
            enabledToggle.type = "checkbox";
            enabledToggle.checked = row.enabled;
            enabledToggle.addEventListener("change", function () {
                toggleScheduleRow(row.id);
            });
            tdEnabled.appendChild(enabledToggle);
            // Remove button
            const tdRemove = tr.insertCell();
            const removeBtn = document.createElement("button");
            removeBtn.textContent = "Remove";
            removeBtn.className = "remove-btn";
            removeBtn.addEventListener("click", function () {
                removeScheduleRow(row.id);
            });
            tdRemove.appendChild(removeBtn);
        });
    }

    function toggleScheduleRow(id) {
        fetch("/api/schedule/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id })
        }).then(fetchState);
    }

    function removeScheduleRow(id) {
        fetch("/api/schedule/remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id })
        }).then(fetchState);
    }

    // Add row
    addRowBtn.addEventListener("click", function () {
        const time = newTimeInput.value.trim();
        const action = newActionInput.value.trim();
        if (!time || !action) {
            alert("Please enter both time and action.");
            return;
        }
        fetch("/api/schedule/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ time, action })
        }).then(() => {
            newTimeInput.value = "";
            newActionInput.value = "";
            fetchState();
        });
    });

    // Initial load
    fetchState();
});