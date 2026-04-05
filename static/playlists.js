(function () {
    const config = window.playlistsConfig || {};
    window.availableLibraries = window.availableLibraries || { movie: [], show: [] };
    window.librariesLoadedCallbacks = window.librariesLoadedCallbacks || [];
    window.librariesLoaded = window.librariesLoaded || false;
    let viewerLoaded = false;

    function getCsrfHeaders(contentType) {
        const headers = { 'X-CSRFToken': config.csrfToken || '' };
        if (contentType) {
            headers['Content-Type'] = contentType;
        }
        return headers;
    }

    function disableRunButtonsForSetup() {
        if (!config.setupIncomplete) {
            return;
        }
        document.querySelectorAll('.btn-sync').forEach((btn) => {
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
            btn.style.pointerEvents = 'none';
            btn.disabled = true;
            btn.setAttribute('disabled', 'disabled');
            btn.title = 'Complete setup steps above first';
        });
    }

    function fetchAvailableLibraries() {
        if (!config.availableLibrariesUrl) {
            return;
        }
        fetch(config.availableLibrariesUrl, { credentials: 'same-origin' })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then((data) => {
                if (data.status === 'success') {
                    window.availableLibraries = data.libraries || { movie: [], show: [] };
                    window.librariesLoaded = true;
                    window.librariesLoadedCallbacks.forEach((cb) => cb());
                    window.librariesLoadedCallbacks = [];
                } else {
                    console.error('Failed to fetch libraries:', data.message);
                }
            })
            .catch((err) => console.error('Failed to fetch libraries:', err));
    }

    window.onLibrariesLoaded = function (callback) {
        if (window.librariesLoaded) {
            callback();
        } else {
            window.librariesLoadedCallbacks.push(callback);
        }
    };

    window.saveGlobalTime = function () {
        const input = document.getElementById('globalTime');
        const feedback = document.getElementById('save-time-feedback');
        const time = input ? input.value : '';
        fetch(config.saveScheduleTimeUrl, {
            method: 'POST',
            headers: getCsrfHeaders('application/x-www-form-urlencoded'),
            body: 'time=' + encodeURIComponent(time)
        })
            .then((response) => response.json())
            .then((data) => {
                if (data.status === 'success') {
                    if (feedback) {
                        feedback.style.display = 'inline';
                        feedback.textContent = 'Saved';
                        setTimeout(() => { feedback.style.display = 'none'; }, 2500);
                    }
                } else {
                    alert(data.message || 'Could not save time');
                }
            })
            .catch(() => alert('Could not save schedule time'));
    };

    window.toggleLibrarySelector = function (key) {
        const modeEl = document.getElementById('library-mode-' + key);
        const selectorEl = document.getElementById('library-selector-' + key);
        if (modeEl && selectorEl) {
            selectorEl.style.display = modeEl.value === 'selected' ? 'block' : 'none';
        }
        window.saveSettings(key);
    };

    window.openTab = function (evt, tabName) {
        Array.from(document.getElementsByClassName('tab-content')).forEach((panel) => {
            panel.style.display = 'none';
            panel.classList.remove('active');
        });
        Array.from(document.getElementsByClassName('tab-btn')).forEach((tab) => tab.classList.remove('active'));
        const selected = document.getElementById(tabName);
        if (selected) {
            selected.style.display = 'block';
            setTimeout(() => selected.classList.add('active'), 10);
        }
        if (evt && evt.currentTarget) {
            evt.currentTarget.classList.add('active');
        }
    };

    window.refreshLibraryBrowser = function () {
        viewerLoaded = false;
        const loading = document.getElementById('viewer-loading');
        const grid = document.getElementById('viewer-grid');
        if (loading) loading.style.display = 'block';
        if (grid) {
            grid.style.display = 'none';
            grid.innerHTML = '';
        }
        loadLiveCollections();
    };

    function loadLiveCollections() {
        if (viewerLoaded || !config.getPlexCollectionsUrl) {
            return;
        }
        fetch(config.getPlexCollectionsUrl)
            .then((response) => response.json())
            .then((data) => {
                const loading = document.getElementById('viewer-loading');
                const grid = document.getElementById('viewer-grid');
                if (loading) loading.style.display = 'none';
                if (!grid) return;
                grid.style.display = 'grid';
                if (data.status === 'success' && data.collections.length > 0) {
                    let html = '';
                    data.collections.forEach((c) => {
                        const thumb = (c.thumb && (c.thumb.startsWith('http://') || c.thumb.startsWith('https://')))
                            ? c.thumb : 'https://via.placeholder.com/200x300?text=No+Art';
                        const url = (c.url && (c.url.startsWith('http://') || c.url.startsWith('https://'))) ? c.url : '#';
                        const keyPath = escapeHtml(String(c.keyPath || c.key || ''));
                        html += `
                    <div class="viewer-card" data-url="${escapeHtml(url)}" role="button" tabindex="0">
                        <img src="${escapeHtml(thumb)}" style="width:100%; height:100%; object-fit:cover;" alt="">
                        <div class="viewer-badge">${escapeHtml(String(c.count || ''))}</div>
                        <div class="viewer-info">
                            <div style="font-weight:bold; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(String(c.title || ''))}</div>
                            <div style="font-size:0.8em; color:#ccc;">${escapeHtml(String(c.library || ''))}</div>
                            <div class="viewer-visibility" onclick="event.stopPropagation();">
                                <label class="viewer-check"><input type="checkbox" class="viewer-check-home" data-keypath="${keyPath}" ${c.visible_home ? 'checked' : ''}> Home</label>
                                <label class="viewer-check"><input type="checkbox" class="viewer-check-library" data-keypath="${keyPath}" ${c.visible_library ? 'checked' : ''}> Library</label>
                                <label class="viewer-check"><input type="checkbox" class="viewer-check-friends" data-keypath="${keyPath}" ${c.visible_friends ? 'checked' : ''}> Friends</label>
                            </div>
                        </div>
                    </div>`;
                    });
                    grid.innerHTML = html;
                    grid.querySelectorAll('.viewer-card').forEach((card) => {
                        card.addEventListener('click', function (event) {
                            if (event.target.closest('.viewer-visibility')) return;
                            const url = this.getAttribute('data-url');
                            if (url && url !== '#' && (url.startsWith('http://') || url.startsWith('https://'))) {
                                window.open(url, '_blank');
                            }
                        });
                    });
                    grid.querySelectorAll('.viewer-check-home, .viewer-check-library, .viewer-check-friends').forEach((input) => {
                        input.addEventListener('change', function () {
                            const keyPath = this.getAttribute('data-keypath');
                            if (!keyPath) return;
                            const card = this.closest('.viewer-card');
                            const homeEl = card.querySelector('.viewer-check-home');
                            const libEl = card.querySelector('.viewer-check-library');
                            const friendsEl = card.querySelector('.viewer-check-friends');
                            fetch(config.plexCollectionVisibilityUrl, {
                                method: 'POST',
                                headers: getCsrfHeaders('application/json'),
                                body: JSON.stringify({
                                    keyPath: keyPath,
                                    visible_home: homeEl ? homeEl.checked : true,
                                    visible_library: libEl ? libEl.checked : true,
                                    visible_friends: friendsEl ? friendsEl.checked : false
                                })
                            })
                                .then((response) => response.json())
                                .then((result) => {
                                    if (result.status !== 'success') {
                                        alert(result.message || 'Could not update visibility');
                                    } else if (result.message) {
                                        const banner = document.createElement('div');
                                        banner.className = 'viewer-save-banner';
                                        banner.textContent = result.message;
                                        grid.insertBefore(banner, grid.firstChild);
                                        setTimeout(() => banner.remove(), 8000);
                                    }
                                })
                                .catch(() => alert('Request failed'));
                        });
                    });
                    viewerLoaded = true;
                } else {
                    grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:50px; color:#666;">No collections found. Make sure you have at least one Movie or TV library in Plex with collections. If you just created some, try <strong>Refresh list</strong> above.</div>';
                }
            })
            .catch(() => {
                const loader = document.getElementById('viewer-loading');
                const grid = document.getElementById('viewer-grid');
                if (loader) loader.style.display = 'none';
                if (grid) {
                    grid.style.display = 'grid';
                    grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:50px; color:#e74c3c;">Failed to load collections. Check Plex connection in Settings and try <strong>Refresh list</strong>.</div>';
                }
            });
    }

    function checkCacheStatus() {
        if (!config.cacheStatusUrl) {
            return;
        }
        fetch(config.cacheStatusUrl)
            .then((response) => response.json())
            .then((data) => {
                document.querySelectorAll('.btn-sync').forEach((button) => {
                    if (config.setupIncomplete) {
                        return;
                    }
                    if (data.running) {
                        button.disabled = true;
                        button.innerText = 'System Busy...';
                        button.style.opacity = '0.5';
                        button.style.cursor = 'not-allowed';
                    } else {
                        button.disabled = false;
                        button.style.opacity = '1';
                        button.style.cursor = 'pointer';
                        button.innerText = (button.id && button.id.startsWith('btn-custom')) ? 'Sync Now' : 'Run Now';
                    }
                });
            });
    }

    const playlistsTypeKey = 'seekandwatch_playlists_type';

    window.filterType = function (type) {
        const nextType = (type === 'tv') ? 'tv' : 'movie';
        try { localStorage.setItem(playlistsTypeKey, nextType); } catch (e) {}
        const movieBtn = document.getElementById('btn-movie');
        const tvBtn = document.getElementById('btn-tv');
        if (movieBtn) movieBtn.classList.remove('active');
        if (tvBtn) tvBtn.classList.remove('active');
        const activeBtn = document.getElementById('btn-' + nextType);
        if (activeBtn) activeBtn.classList.add('active');
        document.querySelectorAll('.playlist-card').forEach((card) => {
            card.style.display = (card.dataset.type === nextType) ? 'flex' : 'none';
        });
        document.querySelectorAll('.category-block').forEach((block) => {
            const grid = block.querySelector('.playlist-grid');
            if (!grid) return;
            let hasVisible = false;
            grid.querySelectorAll('.playlist-card').forEach((card) => {
                if (card.style.display !== 'none') hasVisible = true;
            });
            block.style.display = hasVisible ? '' : 'none';
            const header = block.querySelector('.category-header');
            if (header) header.style.display = hasVisible ? 'flex' : 'none';
        });
        restoreOpenCategories();
    };

    function getCurrentFilter() {
        const active = document.querySelector('.type-toggle-btn.active');
        return (active && active.id === 'btn-tv') ? 'tv' : 'movie';
    }

    function saveOpenCategories() {
        const filter = getCurrentFilter();
        const open = [];
        document.querySelectorAll('.category-block').forEach((block) => {
            const grid = block.querySelector('.playlist-grid');
            if (grid && grid.id && !block.classList.contains('category-block--collapsed')) {
                open.push(grid.id);
            }
        });
        try { sessionStorage.setItem('playlist-open-categories-' + filter, JSON.stringify(open)); } catch (e) {}
    }

    function restoreOpenCategories() {
        const filter = getCurrentFilter();
        try {
            const raw = sessionStorage.getItem('playlist-open-categories-' + filter);
            if (!raw) return;
            const open = JSON.parse(raw);
            if (!Array.isArray(open) || open.length === 0) return;
            document.querySelectorAll('.category-block').forEach((block) => {
                const grid = block.querySelector('.playlist-grid');
                const header = block.querySelector('.category-header--toggle');
                const chevron = block.querySelector('.category-chevron');
                if (!grid || !grid.id || open.indexOf(grid.id) === -1) return;
                block.classList.remove('category-block--collapsed');
                grid.hidden = false;
                grid.style.display = 'grid';
                if (header) header.setAttribute('aria-expanded', 'true');
                if (chevron) chevron.textContent = 'v';
            });
        } catch (e) {}
    }

    function initCategoryToggles() {
        document.querySelectorAll('.category-header--toggle').forEach((btn) => {
            btn.addEventListener('click', function () {
                const block = this.closest('.category-block');
                const grid = block && block.querySelector('.playlist-grid');
                if (!block || !grid) return;
                const isCollapsed = block.classList.toggle('category-block--collapsed');
                grid.hidden = isCollapsed;
                grid.style.display = isCollapsed ? 'none' : 'grid';
                this.setAttribute('aria-expanded', !isCollapsed);
                const chevron = this.querySelector('.category-chevron');
                if (chevron) chevron.textContent = isCollapsed ? '>' : 'v';
                saveOpenCategories();
            });
        });
    }

    window.previewCollection = function (key, title) {
        const titleEl = document.getElementById('preview-title');
        const grid = document.getElementById('preview-grid');
        const modal = document.getElementById('preview-modal');
        if (titleEl) titleEl.innerText = 'Preview: ' + title;
        if (grid) grid.innerHTML = '<div style="text-align:center; grid-column:1/-1; padding:20px; color:#aaa;">Loading live data from TMDB...</div>';
        if (modal) modal.style.display = 'block';
        document.body.style.overflow = 'hidden';
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        fetch(config.previewPresetItemsBase + encodeURIComponent(key), { signal: controller.signal })
            .then((response) => response.json())
            .then((data) => {
                clearTimeout(timeout);
                if (!grid) return;
                if (data.status === 'success') {
                    let html = '';
                    data.items.forEach((item) => {
                        const opacity = item.owned ? '1' : '0.6';
                        const status = item.owned ? 'Owned' : 'Missing';
                        const poster = item.poster_path ? 'https://image.tmdb.org/t/p/w200' + item.poster_path : 'https://via.placeholder.com/200x300?text=No+Poster';
                        const vote = (item.vote_average || 0) * 10;
                        const pct = Math.round(vote) + '%';
                        const ratingBadge = `<span class="preview-badge" style="background:${vote >= 70 ? '#2ecc71' : (vote >= 50 ? '#f1c40f' : '#e74c3c')}">${pct}</span>`;
                        html += `<div class="preview-item" style="opacity: ${opacity};">
                    <img src="${escapeHtml(poster)}" class="preview-poster" alt="">
                    ${ratingBadge}
                    <div class="preview-title">${escapeHtml(String(item.title || ''))}</div>
                    <div class="preview-meta">${escapeHtml(String(item.year || ''))} | ${escapeHtml(String(status || ''))}</div>
                </div>`;
                    });
                    grid.innerHTML = html;
                } else {
                    grid.innerHTML = `<div style="color:var(--error); grid-column:1/-1; text-align:center;">Error: ${(data.message || 'Unknown error').replace(/</g, '&lt;')}</div>`;
                }
            })
            .catch(() => {
                clearTimeout(timeout);
                if (grid) {
                    grid.innerHTML = '<div style="color:var(--error); grid-column:1/-1; text-align:center;">Request failed or timed out.</div>';
                }
            });
    };

    window.closePreviewModal = function () {
        const modal = document.getElementById('preview-modal');
        if (modal) {
            modal.style.display = 'none';
            document.body.style.overflow = '';
        }
    };

    window.deleteCollection = function (key, ev) {
        if (!confirm('Delete this collection from the app and from Plex?')) return;
        const btn = (ev && ev.target) ? ev.target : null;
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Deleting...';
        }
        fetch(config.deleteCollectionBase + encodeURIComponent(key), {
            method: 'POST',
            headers: getCsrfHeaders()
        })
            .then((response) => response.json())
            .then((data) => {
                if (data.status === 'success') {
                    location.reload();
                } else {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = 'Delete';
                    }
                    alert(data.message || 'Could not delete collection.');
                }
            })
            .catch(() => {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Delete';
                }
                alert('Request failed. Could not delete collection.');
            });
    };

    window.deleteCustom = function (key) {
        window.deleteCollection(key);
    };

    window.createCollection = function (key) {
        const btn = document.getElementById('btn-' + key);
        if (!btn) return;
        const originalText = btn.innerText;
        btn.disabled = true;
        btn.innerText = 'Processing...';
        btn.style.background = '#555';
        const body = JSON.stringify({
            visibility_home: !!document.getElementById('visibility-home-' + key)?.checked,
            visibility_library: !!document.getElementById('visibility-library-' + key)?.checked,
            visibility_friends: !!document.getElementById('visibility-friends-' + key)?.checked
        });
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 60000);
        fetch(config.createCollectionBase + encodeURIComponent(key), {
            method: 'POST',
            headers: getCsrfHeaders('application/json'),
            body: body,
            signal: controller.signal
        })
            .then((response) => response.json())
            .then((data) => {
                clearTimeout(timeout);
                if (data.status === 'success') {
                    btn.innerText = 'Done';
                    btn.style.background = 'var(--accent-color)';
                    alert(data.message);
                    const actionsRow = btn.closest('.playlist-control-section--actions');
                    if (actionsRow && !actionsRow.querySelector('.btn-delete-inline')) {
                        const delBtn = document.createElement('button');
                        delBtn.type = 'button';
                        delBtn.className = 'btn-delete-inline';
                        delBtn.title = 'Remove from app and Plex';
                        delBtn.textContent = 'Delete';
                        delBtn.onclick = function (event) { window.deleteCollection(key, event); };
                        actionsRow.appendChild(delBtn);
                    }
                } else {
                    btn.innerText = 'Error';
                    btn.style.background = '#e74c3c';
                    alert(data.message);
                }
                setTimeout(() => {
                    btn.innerText = originalText;
                    btn.disabled = false;
                    btn.style.background = '#333';
                }, 3000);
            })
            .catch(() => {
                clearTimeout(timeout);
                btn.innerText = originalText;
                btn.disabled = false;
                btn.style.background = '#333';
                alert('Request failed or timed out. Please try again.');
            });
    };

    window.saveSettings = function (key) {
        const freq = document.getElementById('freq-' + key)?.value || 'manual';
        const sync = document.getElementById('sync-' + key)?.value || 'sync';
        const visibleHome = !!document.getElementById('visibility-home-' + key)?.checked;
        const visibleLibrary = !!document.getElementById('visibility-library-' + key)?.checked;
        const visibleFriends = !!document.getElementById('visibility-friends-' + key)?.checked;
        const libraryMode = document.getElementById('library-mode-' + key)?.value || 'all';
        const librarySelect = document.getElementById('libraries-' + key);
        let targetLibraries = [];
        if (librarySelect && libraryMode === 'selected') {
            targetLibraries = Array.from(librarySelect.selectedOptions).map((opt) => opt.value).filter((value) => value !== '__all__');
        }

        fetch(config.scheduleCollectionUrl, {
            method: 'POST',
            headers: getCsrfHeaders('application/x-www-form-urlencoded'),
            body: `preset_key=${encodeURIComponent(key)}&frequency=${encodeURIComponent(freq)}&sync_mode=${encodeURIComponent(sync)}&visibility_home=${visibleHome ? '1' : '0'}&visibility_library=${visibleLibrary ? '1' : '0'}&visibility_friends=${visibleFriends ? '1' : '0'}&target_library_mode=${encodeURIComponent(libraryMode)}&target_libraries=${encodeURIComponent(JSON.stringify(targetLibraries))}`
        })
            .then((response) => response.json())
            .then((data) => {
                const feedback = document.getElementById('schedule-save-feedback');
                if (data.status === 'success' && feedback) {
                    feedback.textContent = 'Settings saved';
                    feedback.style.display = 'inline';
                    setTimeout(() => { feedback.style.display = 'none'; }, 2500);
                } else if (data.message) {
                    alert(data.message);
                }
            })
            .catch(() => alert('Could not save settings'));

        fetch(config.plexCollectionVisibilityUrl, {
            method: 'POST',
            headers: getCsrfHeaders('application/json'),
            body: JSON.stringify({
                preset_key: key,
                visible_home: visibleHome,
                visible_library: visibleLibrary,
                visible_friends: visibleFriends
            })
        }).then((response) => response.json()).then((data) => {
            if (data.status !== 'success' && data.message && !data.message.includes('Collection not found')) {
                console.warn('Visibility update:', data.message);
            }
        }).catch(() => {});
    };

    document.addEventListener('DOMContentLoaded', () => {
        disableRunButtonsForSetup();
        fetchAvailableLibraries();
        let savedType = 'movie';
        try { savedType = localStorage.getItem(playlistsTypeKey) || 'movie'; } catch (e) {}
        window.filterType(savedType);
        restoreOpenCategories();
        initCategoryToggles();
        if (document.getElementById('tab-viewer')) {
            loadLiveCollections();
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        const preview = document.getElementById('preview-modal');
        if (preview && preview.style.display === 'block') {
            window.closePreviewModal();
        }
    });

    setInterval(checkCacheStatus, 2000);
})();
