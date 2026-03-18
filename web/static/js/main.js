const sel1 = document.getElementById("creature-1");
const sel2 = document.getElementById("creature-2");

// Populate both selects from the creatures API
fetch("/api/creatures")
    .then(r => r.json())
    .then(creatures => {
        sel1.innerHTML = "";
        sel2.innerHTML = "";
        for (const c of creatures) {
            sel1.appendChild(new Option(c.name, c.path));
            sel2.appendChild(new Option(c.name, c.path));
        }
        // Default to different selections if possible
        if (creatures.length > 1) sel2.selectedIndex = 1;
    })
    .catch(() => {
        sel1.innerHTML = '<option value="">Failed to load</option>';
        sel2.innerHTML = '<option value="">Failed to load</option>';
    });

function startCombat(event) {
    const c1 = sel1.value;
    const c2 = sel2.value;
    if (!c1 || !c2) {
        event.preventDefault();
        return;
    }
    sessionStorage.setItem("combat_ready", "1");
    sessionStorage.setItem("creature_1", c1);
    sessionStorage.setItem("creature_2", c2);
}
