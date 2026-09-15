// Starting page interactivity.
// Both entry points lead to the chat interface, per the validated wireframe,
// there is no longer a separate address-input step on this page.
 
document.addEventListener('DOMContentLoaded', () => {
  const checkNowBtn = document.getElementById('checkNowBtn');
  const capabilitiesBtn = document.getElementById('capabilitiesBtn');
 
  function goToChat() {
    window.location.href = '../chatbox-page/index.html';
  }
 
  checkNowBtn.addEventListener('click', goToChat);
  capabilitiesBtn.addEventListener('click', goToChat);
});
 