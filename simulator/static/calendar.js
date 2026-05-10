// Calendar interactions for the simulator.
// Clicking an available cell fetches the booking modal partial and injects it.

function openModal(courtType, court, hour) {
  const url = `/Member/CourtReservation/modal?type=${encodeURIComponent(courtType)}&court=${encodeURIComponent(court)}&hour=${encodeURIComponent(hour)}`;
  fetch(url, { credentials: "same-origin" })
    .then((r) => {
      if (r.status === 409) {
        alert("Slot no longer available");
        throw new Error("conflict");
      }
      return r.text();
    })
    .then((html) => {
      const host = document.getElementById("booking-modal-host");
      host.innerHTML = html;
    })
    .catch((err) => console.warn("Could not open modal:", err));
}

function closeModal() {
  const host = document.getElementById("booking-modal-host");
  if (host) host.innerHTML = "";
}
