async function loadMentions() {
  try {
    const response = await fetch('data.json?' + new Date().getTime()); // prevent cache
    if (!response.ok) throw new Error('Failed to fetch data.json');
    const data = await response.json();

    const container = document.getElementById('mentions');
    container.innerHTML = '';

    if (Object.keys(data).length === 0) {
      container.textContent = 'No mention data available.';
      return;
    }

    const list = document.createElement('ul');
    for (const [token, count] of Object.entries(data)) {
      const item = document.createElement('li');
      item.textContent = `${token}: ${count}`;
      list.appendChild(item);
    }
    container.appendChild(list);
  } catch (e) {
    document.getElementById('mentions').textContent = 'Error loading data.';
    console.error(e);
  }
}

loadMentions();
