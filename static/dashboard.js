(function () {
    const config = window.dashboardConfig || {};
    const loader = document.getElementById('nuclear-loader');
    const searchInput = document.getElementById('main-search');
    const resultsDiv = document.getElementById('search-results');
    let debounceTimer;
    let currentTrendingType = 'movie';

    function showLoader() {
        if (loader) {
            loader.style.display = 'flex';
        }
    }

    function hideSearchResults() {
        if (resultsDiv) {
            resultsDiv.style.display = 'none';
        }
    }

    function fetchSystemHealth() {
        if (!config.healthStatusUrl) {
            return;
        }
        fetch(config.healthStatusUrl)
            .then((response) => response.json())
            .then((data) => {
                Object.keys(data).forEach((service) => {
                    const el = document.getElementById(`health-${service}`);
                    if (!el) {
                        return;
                    }
                    const dot = el.querySelector('.health-dot');
                    const status = el.querySelector('.health-status');
                    const info = data[service] || {};
                    if (dot) {
                        dot.className = 'health-dot';
                        dot.classList.add(`status-${info.status || 'unknown'}`);
                    }
                    if (status) {
                        status.innerText = info.message || 'Unknown';
                    }
                });
            })
            .catch((err) => console.error('Health check failed:', err));
    }

    function submitManualQuery(title) {
        if (!config.reviewHistoryUrl || !config.csrfToken) {
            return;
        }
        showLoader();
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = config.reviewHistoryUrl;

        const csrfInput = document.createElement('input');
        csrfInput.type = 'hidden';
        csrfInput.name = 'csrf_token';
        csrfInput.value = config.csrfToken;
        form.appendChild(csrfInput);

        const queryInput = document.createElement('input');
        queryInput.type = 'hidden';
        queryInput.name = 'manual_query';
        queryInput.value = title;
        form.appendChild(queryInput);

        const typeInput = document.createElement('input');
        typeInput.type = 'hidden';
        typeInput.name = 'media_type';
        typeInput.value = 'movie';
        form.appendChild(typeInput);

        document.body.appendChild(form);
        setTimeout(() => form.submit(), 50);
    }

    function renderSearchResults(items) {
        if (!resultsDiv) {
            return;
        }
        if (!items || !items.length) {
            hideSearchResults();
            return;
        }
        let html = '';
        items.forEach((item) => {
            const safeTitleAttr = String(item.title || '')
                .replace(/\\/g, '\\\\')
                .replace(/'/g, "\\'")
                .replace(/"/g, '&quot;');
            const posterSrc = item.poster && String(item.poster).startsWith('/')
                ? 'https://image.tmdb.org/t/p/w92' + item.poster
                : '';
            html += `<div class="search-result-item" onclick="selectItem('${safeTitleAttr}')">
                <img src="${posterSrc || 'https://via.placeholder.com/92x138?text=No+Poster'}" class="search-poster-thumb" onerror="this.style.display='none'" alt="">
                <div><div class="fw-bold">${escapeHtml(String(item.title || ''))}</div><div class="fs-small text-muted">${escapeHtml(String(item.year || ''))}</div></div></div>`;
        });
        resultsDiv.innerHTML = html;
        resultsDiv.style.display = 'block';
    }

    function loadTrending(type) {
        currentTrendingType = type;
        document.querySelectorAll('.t-tab').forEach((button) => button.classList.remove('active'));
        const activeTab = document.getElementById('tab-' + type);
        if (activeTab) {
            activeTab.classList.add('active');
        }

        const grid = document.getElementById('trending-grid');
        if (!grid || !config.localTrendingUrl) {
            return;
        }

        grid.innerHTML = '<div class="grid-col-full text-center text-muted" style="padding:50px;">Loading Tautulli stats...</div>';
        const daysInput = document.getElementById('trending-days');
        const days = daysInput ? parseInt(daysInput.value, 10) || 30 : 30;

        const trendController = new AbortController();
        const trendTimeout = setTimeout(() => trendController.abort(), 15000);
        fetch(config.localTrendingUrl + '?type=' + encodeURIComponent(type) + '&days=' + days, { signal: trendController.signal })
            .then((response) => response.json())
            .then((data) => {
                clearTimeout(trendTimeout);
                if (data.status === 'success' && data.items.length > 0) {
                    let html = '';
                    data.items.forEach((item, idx) => {
                        const poster = item.poster_path && String(item.poster_path).startsWith('/')
                            ? 'https://image.tmdb.org/t/p/w200' + item.poster_path
                            : 'https://via.placeholder.com/200x300?text=No+Poster';
                        const safeTitle = escapeHtml(String(item.title || ''));
                        const safeTitleAttr = String(item.title || '')
                            .replace(/\\/g, '\\\\')
                            .replace(/'/g, "\\'")
                            .replace(/"/g, '&quot;');
                        html += `
                        <div class="t-card" title="${safeTitleAttr}" onclick="selectItem('${safeTitleAttr}')">
                            <div class="t-rank">#${idx + 1}</div>
                            <img src="${poster}" class="t-poster" alt="">
                            <div class="t-info">${safeTitle}</div>
                        </div>`;
                    });
                    grid.innerHTML = html;
                } else {
                    grid.innerHTML = '<div class="grid-col-full text-center text-muted" style="padding:50px;">No trending data found.</div>';
                }
            })
            .catch((err) => {
                clearTimeout(trendTimeout);
                console.error(err);
                grid.innerHTML = '<div class="grid-col-full text-center text-muted" style="padding:50px; color:#e74c3c;">Failed to load stats. Please try again.</div>';
            });
    }

    window.nuclearSubmit = function (type) {
        showLoader();
        const input = document.getElementById('mediaTypeInput');
        if (input) {
            input.value = type;
        }
        setTimeout(() => {
            const form = document.getElementById('mainScanForm');
            if (form) {
                form.submit();
            }
        }, 50);
    };

    window.nuclearLucky = function () {
        showLoader();
        setTimeout(() => {
            const form = document.getElementById('luckyForm');
            if (form) {
                form.submit();
            }
        }, 50);
    };

    window.selectItem = submitManualQuery;
    window.loadTrending = loadTrending;
    window.findSimilarToTrending = function () {
        if (config.recommendFromTrendingUrl) {
            window.location.href = config.recommendFromTrendingUrl + '?type=' + encodeURIComponent(currentTrendingType);
        }
    };

    document.addEventListener('DOMContentLoaded', function () {
        if (loader && document.body) {
            document.body.appendChild(loader);
            loader.style.display = 'none';
        }

        fetchSystemHealth();
        setInterval(fetchSystemHealth, 60000);

        if (searchInput && resultsDiv && config.tmdbSearchProxyUrl) {
            searchInput.addEventListener('input', function () {
                clearTimeout(debounceTimer);
                const query = this.value.trim();
                if (query.length < 2) {
                    hideSearchResults();
                    return;
                }
                debounceTimer = setTimeout(() => {
                    fetch(config.tmdbSearchProxyUrl + '?query=' + encodeURIComponent(query) + '&type=movie')
                        .then((response) => response.json())
                        .then((data) => renderSearchResults(data.results || []))
                        .catch(() => hideSearchResults());
                }, 300);
            });

            document.addEventListener('click', function (event) {
                if (!searchInput.contains(event.target) && !resultsDiv.contains(event.target)) {
                    hideSearchResults();
                }
            });
        }

        if (document.getElementById('trending-grid')) {
            loadTrending('movie');
        }
    });
})();
