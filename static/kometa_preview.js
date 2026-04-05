(function () {
    window.overlaySettingsMap = {
        content_rating_au: ['builder_level', 'addon_position'],
        commonsense: ['builder_level', 'addon_position'],
        content_rating_de: ['builder_level', 'addon_position'],
        content_rating_nz: ['builder_level', 'addon_position'],
        content_rating_uk: ['builder_level', 'addon_position'],
        content_rating_us_movie: ['addon_position'],
        content_rating_us_show: ['builder_level', 'addon_position'],
        aspect: [],
        audio_codec: ['builder_level', 'style'],
        language_count: ['builder_level', 'minimum', 'style'],
        languages: ['builder_level'],
        resolution: ['builder_level'],
        runtimes: ['builder_level'],
        versions: ['builder_level'],
        network: ['builder_level'],
        studio: ['builder_level'],
        direct_play: ['builder_level'],
        ratings: ['builder_level'],
        video_format: ['builder_level']
    };

    const overlayPreviewSamples = {
        ribbon: { position: 'br', label: 'TOP 250', class: 'ribbon', bottomPct: 0 },
        episode_info: { position: 'bl', seasonEpisode: true },
        mediastinger: { position: 'tr', label: 'Post-Credit', class: 'misc', topPct: 14.33 },
        status: { position: 'tl', label: 'Ended', class: 'misc', topPct: 22 },
        content_rating_au: { position: 'bl', label: 'M', class: 'rating', bottomPct: 18 },
        commonsense: { position: 'bl', label: '8+', class: 'rating', bottomPct: 18 },
        content_rating_de: { position: 'bl', label: 'FSK 16', class: 'rating', bottomPct: 18 },
        content_rating_nz: { position: 'bl', label: 'M', class: 'rating', bottomPct: 18 },
        content_rating_uk: { position: 'bl', label: '15', class: 'rating', bottomPct: 18 },
        content_rating_us_movie: { position: 'bl', label: 'PG-13', class: 'rating', bottomPct: 18 },
        content_rating_us_show: { position: 'bl', label: 'TV-MA', class: 'rating', bottomPct: 18 },
        aspect: { position: 'bc', label: '2.35:1', class: 'media', bottomPct: 0 },
        audio_codec: { position: 'tc', label: 'Atmos', class: 'media', topPct: 1 },
        language_count: { position: 'bc', label: 'Dual', class: 'misc', bottomPct: 2 },
        languages: { position: 'tl', label: 'EN', class: 'misc', topPct: 1 },
        resolution: { position: 'tl', label: '4K', class: 'media', topPct: 1 },
        runtimes: { position: 'br', label: '2h 15m', class: 'misc', bottomPct: 2 },
        versions: { position: 'br', label: '2', class: 'misc', bottomPct: 22 },
        network: { position: 'bl', label: 'HBO', class: 'misc', bottomPct: 34 },
        streaming: { position: 'bl', label: 'Netflix', class: 'misc', bottomPct: 26 },
        studio: { position: 'bl', label: 'Pixar', class: 'misc', bottomPct: 10 },
        direct_play: { position: 'bc', label: 'Direct Play Only', class: 'media', bottomPct: 10 },
        ratings: { position: 'tl', label: '8.5', class: 'misc', topPct: 50 },
        video_format: { position: 'bl', label: 'REMUX', class: 'media', bottomPct: 2 }
    };

    function getTemplateVars() {
        return window.templateVars || {};
    }

    function getActiveOverlaysForPreview() {
        const overlays = [];
        document.querySelectorAll('.t-opt.ovl:checked').forEach((cb) => {
            const item = cb.closest('.k-check-item');
            if (item && !item.classList.contains('hidden')) {
                overlays.push(cb.value);
            }
        });
        return overlays;
    }

    function renderOverlayBadgesInto(container, active, options) {
        if (!container) return;
        const templateVars = getTemplateVars();
        const settings = options || {};
        const showSeasonBadgeOnly = !!settings.showSeasonBadgeOnly;
        const showSeasonEpisodeGroup = !!settings.showSeasonEpisodeGroup;
        container.innerHTML = '';
        const hasSeasonEpisode = active.some((key) => overlayPreviewSamples[key] && overlayPreviewSamples[key].seasonEpisode);
        const blOffset = (hasSeasonEpisode && (showSeasonBadgeOnly || showSeasonEpisodeGroup)) ? 22 : 0;

        if (hasSeasonEpisode && showSeasonBadgeOnly) {
            const seasonBadge = document.createElement('span');
            seasonBadge.className = 'overlay-preview-badge season-sample pos-bl';
            seasonBadge.textContent = 'S3';
            seasonBadge.title = 'Season overlay sample';
            seasonBadge.style.bottom = '6px';
            seasonBadge.style.left = '6px';
            container.appendChild(seasonBadge);
        }

        if (hasSeasonEpisode && showSeasonEpisodeGroup) {
            const group = document.createElement('div');
            group.className = 'overlay-preview-season-episode-group';
            const seasonBadge = document.createElement('span');
            seasonBadge.className = 'overlay-preview-badge season-sample';
            seasonBadge.textContent = 'S3';
            seasonBadge.title = 'Season overlay sample';
            const episodeBadge = document.createElement('span');
            episodeBadge.className = 'overlay-preview-badge episode-sample';
            episodeBadge.textContent = 'E10';
            episodeBadge.title = 'Episode overlay sample';
            group.appendChild(seasonBadge);
            group.appendChild(episodeBadge);
            container.appendChild(group);
        }

        const positions = { tl: [], tr: [], bl: [], br: [], bc: [], tc: [] };
        active.forEach((key) => {
            const sample = overlayPreviewSamples[key] || { position: 'br', label: key.replace(/_/g, ' '), class: 'misc' };
            if (sample.seasonEpisode) return;
            const pos = sample.position || 'br';
            if (!positions[pos]) positions[pos] = [];
            const customLabel = templateVars[key] && templateVars[key].style;
            const label = (typeof customLabel === 'string' && customLabel.trim()) ? customLabel.trim() : (sample.label || key);
            positions[pos].push({ key, label: String(label), class: sample.class || 'misc', bottomPct: sample.bottomPct, topPct: sample.topPct });
        });

        Object.keys(positions).forEach((pos) => {
            positions[pos].forEach((item) => {
                const span = document.createElement('span');
                span.className = `overlay-preview-badge pos-${pos} ${item.class}`;
                span.textContent = item.label;
                if (pos === 'tl' || pos === 'tr' || pos === 'tc') {
                    span.style.top = (item.topPct != null ? item.topPct : 1) + '%';
                } else if (pos === 'bl' || pos === 'br' || pos === 'bc') {
                    const pct = (item.bottomPct != null ? item.bottomPct : 2);
                    span.style.bottom = blOffset ? `calc(${pct}% + ${blOffset}px)` : (pct + '%');
                }
                container.appendChild(span);
            });
        });
    }

    window.updateOverlayPreview = function () {
        const container = document.getElementById('overlay-preview-badges');
        const emptyEl = document.getElementById('overlay-preview-empty');
        const titleEl = document.getElementById('overlay-preview-title');
        const wrapSingle = document.getElementById('overlay-preview-wrap-single');
        const wrapTv = document.getElementById('overlay-preview-wrap-tv');
        const emptySeason = document.getElementById('overlay-preview-empty-season');
        const emptyEpisode = document.getElementById('overlay-preview-empty-episode');
        if (!container) return;

        const rawLibType = document.getElementById('temp_lib_type')?.value || '';
        const libType = rawLibType === 'show' ? 'tv' : rawLibType;
        if (titleEl) {
            if (libType === 'movie') titleEl.textContent = 'Sample overlay preview (Movie)';
            else if (libType === 'tv') titleEl.textContent = 'Sample overlay preview (TV)';
            else if (libType === 'anime') titleEl.textContent = 'Sample overlay preview (Anime)';
            else titleEl.textContent = 'Sample overlay preview';
        }

        const active = getActiveOverlaysForPreview();
        const isTvOrAnime = (libType === 'tv' || libType === 'anime' || libType === 'show');

        if (isTvOrAnime) {
            if (wrapSingle) wrapSingle.style.display = 'none';
            if (wrapTv) wrapTv.style.display = 'flex';
            const seasonContainer = document.getElementById('overlay-preview-badges-season');
            const episodeContainer = document.getElementById('overlay-preview-badges-episode');
            if (active.length === 0) {
                if (emptySeason) emptySeason.style.display = 'flex';
                if (emptyEpisode) emptyEpisode.style.display = 'flex';
                return;
            }
            if (emptySeason) emptySeason.style.display = 'none';
            if (emptyEpisode) emptyEpisode.style.display = 'none';
            renderOverlayBadgesInto(seasonContainer, active, { showSeasonBadgeOnly: true });
            renderOverlayBadgesInto(episodeContainer, active, { showSeasonEpisodeGroup: true });
        } else {
            if (wrapSingle) wrapSingle.style.display = 'block';
            if (wrapTv) wrapTv.style.display = 'none';
            container.innerHTML = '';
            if (active.length === 0) {
                if (emptyEl) emptyEl.style.display = 'flex';
                return;
            }
            if (emptyEl) emptyEl.style.display = 'none';
            renderOverlayBadgesInto(container, active, { showSeasonEpisodeGroup: true });
        }
    };

    window.switchTab = function (tabName, event) {
        document.querySelectorAll('.k-section').forEach((el) => el.classList.remove('active'));
        document.querySelectorAll('.k-tab').forEach((el) => el.classList.remove('active'));
        const section = document.getElementById('tab-' + tabName);
        if (section) section.classList.add('active');
        const eventTarget = event && event.target ? event.target : window.event?.target;
        if (eventTarget) eventTarget.classList.add('active');
    };

    window.toggleOptions = function () {
        const libName = document.getElementById('temp_lib_name')?.value;
        const wrapper = document.getElementById('options-lock-wrapper');
        const btn = document.getElementById('btn-action');
        if (!wrapper || !btn) return;
        if (!libName) {
            wrapper.classList.add('locked-section');
            btn.disabled = true;
        } else {
            wrapper.classList.remove('locked-section');
            btn.disabled = false;
        }
    };
})();
