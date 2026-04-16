(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        // 1. Identify Entity Type
        let entityType = null;
        if (document.body.classList.contains('model-person')) entityType = 'person';
        else if (document.body.classList.contains('model-location')) entityType = 'location';
        else if (document.body.classList.contains('model-timelineevent')) entityType = 'event';

        if (!entityType) return;

        // 2. Add Google Search Button next to the main name/title field
        const nameFieldId = entityType === 'event' ? 'id_title' : 'id_name';
        const nameField = document.getElementById(nameFieldId);
        if (!nameField) return;

        const searchBtn = document.createElement('button');
        searchBtn.type = 'button';
        searchBtn.className = 'admin-search-btn';
        searchBtn.innerHTML = '🔍 Google Search';
        searchBtn.title = 'Search Google for this ' + entityType;
        nameField.parentNode.appendChild(searchBtn);

        searchBtn.addEventListener('click', function () {
            const nameValue = nameField.value.trim();
            if (!nameValue) {
                alert('Please enter a name or title first.');
                return;
            }

            const query = `${nameValue} ${entityType === 'person' ? 'biography' : entityType === 'location' ? 'history' : ''}`.trim();
            const url = `https://www.google.com/search?q=${encodeURIComponent(query)}`;
            window.open(url, '_blank');
        });

        // 3. Identification of Current User
        const userTools = document.getElementById('user-tools');
        const currentUser = userTools ? userTools.querySelector('strong').textContent.trim().toLowerCase() : null;

        // 4. Add Clone Button if we are on a change page (has an ID in URL)
        const pathParts = window.location.pathname.split('/');
        const objectId = pathParts[pathParts.length - 3] === 'change' ? pathParts[pathParts.length - 2] : null;

        // Check ownership from a potential 'owner' field if it exists on the page
        const ownerField = document.querySelector('.field-owner .readonly, .field-owner div');
        const itemOwner = ownerField ? ownerField.textContent.trim().toLowerCase() : null;

        if (objectId && !document.body.classList.contains('add-form')) {
            // ONLY show clone button if NOT owned by current user
            // We compare case-insensitively and check if either is missing
            const isSelfOwned = currentUser && itemOwner && (currentUser === itemOwner || itemOwner.includes(currentUser));

            if (currentUser && !isSelfOwned) {
                const cloneBtn = document.createElement('button');
                cloneBtn.type = 'button';
                cloneBtn.className = 'admin-clone-btn';
                cloneBtn.innerHTML = '💾 Save a Copy';
                cloneBtn.style.backgroundColor = '#059669';
                cloneBtn.style.color = 'white';
                cloneBtn.style.marginLeft = '10px';
                cloneBtn.style.padding = '5px 15px';
                cloneBtn.style.borderRadius = '4px';
                cloneBtn.style.border = 'none';
                cloneBtn.style.cursor = 'pointer';
                cloneBtn.title = 'Save a copy of this record to your collection so you can edit it';

                if (searchBtn && searchBtn.parentNode) {
                    searchBtn.parentNode.appendChild(cloneBtn);
                }

                cloneBtn.addEventListener('click', function () {
                    const addUrl = window.location.pathname.replace(`/${objectId}/change/`, '/add/') + `?clone_from=${objectId}`;
                    window.location.href = addUrl;
                });
            }
        }

        // 5. Hide List View Clone Buttons for owned items
        if (currentUser) {
            // Use a small delay to ensure all list items are processed if they are dynamic
            setTimeout(() => {
                document.querySelectorAll('.clone-btn-list').forEach(btn => {
                    const owner = btn.getAttribute('data-owner');
                    if (owner && owner.toLowerCase() === currentUser) {
                        btn.style.display = 'none';
                    }
                });
            }, 50);
        }
    });
})();
