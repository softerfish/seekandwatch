"""Collection presets - predefined lists users can sync to plex."""

PLAYLIST_PRESETS = {

# Regional trending
    'trending_us_movies': {'title': 'Trending USA', 'category': 'Regional Trending', 'icon': '🇺🇸', 'media_type': 'movie', 'description': 'Popular movies in the US.', 'tmdb_params': {'watch_region': 'US', 'with_watch_monetization_types': 'flatrate|rent|buy', 'sort_by': 'popularity.desc'}},
    'trending_uk_movies': {'title': 'Trending UK', 'category': 'Regional Trending', 'icon': '🇬🇧', 'media_type': 'movie', 'description': 'Popular movies in the UK.', 'tmdb_params': {'watch_region': 'GB', 'with_watch_monetization_types': 'flatrate|rent|buy', 'sort_by': 'popularity.desc'}},
    'trending_ca_movies': {'title': 'Trending Canada', 'category': 'Regional Trending', 'icon': '🇨🇦', 'media_type': 'movie', 'description': 'Popular movies in Canada.', 'tmdb_params': {'watch_region': 'CA', 'with_watch_monetization_types': 'flatrate|rent|buy', 'sort_by': 'popularity.desc'}},
    
    'trending_us_tv': {'title': 'Trending USA', 'category': 'Regional Trending', 'icon': '🇺🇸', 'media_type': 'tv', 'description': 'Popular TV in the US.', 'tmdb_params': {'watch_region': 'US', 'with_watch_monetization_types': 'flatrate|rent|buy', 'sort_by': 'popularity.desc'}},
    'trending_uk_tv': {'title': 'Trending UK', 'category': 'Regional Trending', 'icon': '🇬🇧', 'media_type': 'tv', 'description': 'Popular TV in the UK.', 'tmdb_params': {'watch_region': 'GB', 'with_watch_monetization_types': 'flatrate|rent|buy', 'sort_by': 'popularity.desc'}},
    'trending_ca_tv': {'title': 'Trending Canada', 'category': 'Regional Trending', 'icon': '🇨🇦', 'media_type': 'tv', 'description': 'Popular TV in Canada.', 'tmdb_params': {'watch_region': 'CA', 'with_watch_monetization_types': 'flatrate|rent|buy', 'sort_by': 'popularity.desc'}},
    
    # International
    'k_drama': {'title': 'K-Dramas', 'category': 'International & World', 'icon': '🇰🇷', 'media_type': 'tv', 'description': 'Korean dramas & romance.', 'tmdb_params': {'with_original_language': 'ko', 'with_genres': '18', 'sort_by': 'popularity.desc'}},
    'anime_movies': {'title': 'Anime Movies', 'category': 'International & World', 'icon': '🗾', 'media_type': 'movie', 'description': 'Japanese animation.', 'tmdb_params': {'with_original_language': 'ja', 'with_genres': '16', 'sort_by': 'popularity.desc'}},
    'bollywood_hits': {'title': 'Bollywood Hits', 'category': 'International & World', 'icon': '🇮🇳', 'media_type': 'movie', 'description': 'Cinema from India.', 'tmdb_params': {'with_original_language': 'hi', 'sort_by': 'popularity.desc'}},
    'nordic_noir': {'title': 'Nordic Noir', 'category': 'International & World', 'icon': '❄️', 'media_type': 'tv', 'description': 'Scandi crime dramas.', 'tmdb_params': {'with_original_language': 'da|sv|no', 'with_genres': '80', 'sort_by': 'vote_average.desc'}},
    'french_cinema': {'title': 'French Cinema', 'category': 'International & World', 'icon': '🇫🇷', 'media_type': 'movie', 'description': 'Art & drama from France.', 'tmdb_params': {'with_original_language': 'fr', 'sort_by': 'popularity.desc'}},
    'british_crime': {'title': 'British Crime', 'category': 'International & World', 'icon': '🇬🇧', 'media_type': 'tv', 'description': 'Gritty UK procedurals.', 'tmdb_params': {'with_origin_country': 'GB', 'with_genres': '80', 'sort_by': 'popularity.desc'}},

    # Decades
    'movies_40s': {'title': 'The 1940s', 'category': 'Decades', 'icon': '🎩', 'media_type': 'movie', 'description': 'Golden Age classics.', 'tmdb_params': {'primary_release_date.gte': '1940-01-01', 'primary_release_date.lte': '1949-12-31', 'sort_by': 'popularity.desc'}},
    'movies_50s': {'title': 'The 1950s', 'category': 'Decades', 'icon': '👗', 'media_type': 'movie', 'description': 'Post-war & Sci-Fi.', 'tmdb_params': {'primary_release_date.gte': '1950-01-01', 'primary_release_date.lte': '1959-12-31', 'sort_by': 'popularity.desc'}},
    'movies_60s': {'title': 'The 1960s', 'category': 'Decades', 'icon': '☮️', 'media_type': 'movie', 'description': 'Counterculture era.', 'tmdb_params': {'primary_release_date.gte': '1960-01-01', 'primary_release_date.lte': '1969-12-31', 'sort_by': 'popularity.desc'}},
    'movies_70s': {'title': 'The 1970s', 'category': 'Decades', 'icon': '🕺', 'media_type': 'movie', 'description': 'Gritty realism.', 'tmdb_params': {'primary_release_date.gte': '1970-01-01', 'primary_release_date.lte': '1979-12-31', 'sort_by': 'popularity.desc'}},
    'movies_80s': {'title': 'The 1980s', 'category': 'Decades', 'icon': '📼', 'media_type': 'movie', 'description': 'Neon & Action.', 'tmdb_params': {'primary_release_date.gte': '1980-01-01', 'primary_release_date.lte': '1989-12-31', 'sort_by': 'popularity.desc'}},
    'movies_90s': {'title': 'The 1990s', 'category': 'Decades', 'icon': '💾', 'media_type': 'movie', 'description': 'Indie boom.', 'tmdb_params': {'primary_release_date.gte': '1990-01-01', 'primary_release_date.lte': '1999-12-31', 'sort_by': 'popularity.desc'}},
    'movies_2000s': {'title': 'The 2000s', 'category': 'Decades', 'icon': '💿', 'media_type': 'movie', 'description': 'New Millennium.', 'tmdb_params': {'primary_release_date.gte': '2000-01-01', 'primary_release_date.lte': '2009-12-31', 'sort_by': 'popularity.desc'}},
    'movies_2010s': {'title': 'The 2010s', 'category': 'Decades', 'icon': '📱', 'media_type': 'movie', 'description': 'Streaming era.', 'tmdb_params': {'primary_release_date.gte': '2010-01-01', 'primary_release_date.lte': '2019-12-31', 'sort_by': 'popularity.desc'}},
    'movies_2020s': {'title': 'The 2020s', 'category': 'Decades', 'icon': '😷', 'media_type': 'movie', 'description': 'Modern cinema.', 'tmdb_params': {'primary_release_date.gte': '2020-01-01', 'sort_by': 'popularity.desc'}},

    # Themes + vibes
    'theme_timetravel': {'title': 'Time Travel', 'category': 'Themes & Vibes', 'icon': '⏳', 'media_type': 'movie', 'description': 'Paradoxes.', 'tmdb_params': {'with_keywords': '4379', 'with_genres': '878', 'sort_by': 'popularity.desc'}},
    'theme_heist': {'title': 'Heist Movies', 'category': 'Themes & Vibes', 'icon': '💰', 'media_type': 'movie', 'description': 'The perfect score.', 'tmdb_params': {'with_keywords': '10051', 'sort_by': 'popularity.desc'}},
    'theme_sports': {'title': 'Sports Dramas', 'category': 'Themes & Vibes', 'icon': '⚾', 'media_type': 'movie', 'description': 'Underdogs & champions.', 'tmdb_params': {'with_keywords': '6075', 'with_genres': '18', 'sort_by': 'popularity.desc'}},
    'theme_musical': {'title': 'Musicals', 'category': 'Themes & Vibes', 'icon': '🎶', 'media_type': 'movie', 'description': 'Singing & dancing.', 'tmdb_params': {'with_genres': '10402', 'sort_by': 'vote_count.desc'}},
    'theme_disaster': {'title': 'Disaster', 'category': 'Themes & Vibes', 'icon': '🌪️', 'media_type': 'movie', 'description': 'End of the world.', 'tmdb_params': {'with_keywords': '4414|10549', 'sort_by': 'revenue.desc'}},
    'theme_highschool': {'title': 'High School', 'category': 'Themes & Vibes', 'icon': '🎒', 'media_type': 'movie', 'description': 'Coming of age.', 'tmdb_params': {'with_keywords': '6270', 'sort_by': 'popularity.desc'}},
    'theme_standup': {'title': 'Stand-Up', 'category': 'Themes & Vibes', 'icon': '🎤', 'media_type': 'movie', 'description': 'Comedy specials.', 'tmdb_params': {'with_keywords': '9716', 'sort_by': 'release_date.desc'}},
    'theme_miniseries': {'title': 'Miniseries', 'category': 'Themes & Vibes', 'icon': '📚', 'media_type': 'tv', 'description': 'Limited series.', 'tmdb_params': {'with_keywords': '11162', 'sort_by': 'vote_average.desc', 'vote_count.gte': '100'}},

    # Awards
    'oscar_winners': {'title': 'Oscar Winners', 'category': 'Awards & Acclaim', 'icon': '🏆', 'media_type': 'movie', 'description': 'Best Picture Winners.', 'tmdb_params': {'with_keywords': '528', 'sort_by': 'vote_average.desc', 'vote_count.gte': '500'}},
    'emmy_winners': {'title': 'Top Rated TV', 'category': 'Awards & Acclaim', 'icon': '📺', 'media_type': 'tv', 'description': 'Critically Acclaimed.', 'tmdb_params': {'vote_average.gte': '8.0', 'vote_count.gte': '500', 'sort_by': 'vote_average.desc'}},
    'sundance_faves': {'title': 'Sundance Hits', 'category': 'Awards & Acclaim', 'icon': '🏔️', 'media_type': 'movie', 'description': 'Festival favorites.', 'tmdb_params': {'with_keywords': '272', 'sort_by': 'popularity.desc'}},
    'critics_choice': {'title': 'Critics Choice', 'category': 'Awards & Acclaim', 'icon': '🧐', 'media_type': 'movie', 'description': 'Rated 8.0+.', 'tmdb_params': {'vote_average.gte': '8.0', 'vote_count.gte': '1000', 'sort_by': 'vote_average.desc'}},

    # Studios + networks
    'studio_a24': {'title': 'A24 Films', 'category': 'Studios & Networks', 'icon': '🅰️', 'media_type': 'movie', 'description': 'Indie horror/drama.', 'tmdb_params': {'with_companies': '41077', 'sort_by': 'release_date.desc'}},
    'studio_pixar': {'title': 'Pixar', 'category': 'Studios & Networks', 'icon': '💡', 'media_type': 'movie', 'description': 'Animation gold.', 'tmdb_params': {'with_companies': '3', 'sort_by': 'popularity.desc'}},
    'studio_ghibli': {'title': 'Studio Ghibli', 'category': 'Studios & Networks', 'icon': '🍃', 'media_type': 'movie', 'description': 'Anime classics.', 'tmdb_params': {'with_companies': '10342', 'sort_by': 'popularity.desc'}},
    'studio_dreamworks': {'title': 'Dreamworks', 'category': 'Studios & Networks', 'icon': '🌙', 'media_type': 'movie', 'description': 'Shrek, Kung Fu Panda.', 'tmdb_params': {'with_companies': '521', 'sort_by': 'popularity.desc'}},
    'studio_blumhouse': {'title': 'Blumhouse', 'category': 'Studios & Networks', 'icon': '👻', 'media_type': 'movie', 'description': 'Modern horror.', 'tmdb_params': {'with_companies': '3172', 'sort_by': 'popularity.desc'}},
    'network_hbo': {'title': 'HBO Series', 'category': 'Studios & Networks', 'icon': '📺', 'media_type': 'tv', 'description': 'Prestige TV.', 'tmdb_params': {'with_networks': '49', 'sort_by': 'vote_average.desc', 'vote_count.gte': '300'}},
    'network_netflix': {'title': 'Netflix Originals', 'category': 'Studios & Networks', 'icon': '🟥', 'media_type': 'tv', 'description': 'Streaming hits.', 'tmdb_params': {'with_networks': '213', 'sort_by': 'popularity.desc'}},
    'network_apple': {'title': 'Apple TV+', 'category': 'Studios & Networks', 'icon': '🍏', 'media_type': 'tv', 'description': 'Apple Originals.', 'tmdb_params': {'with_networks': '2552', 'sort_by': 'popularity.desc'}},

    # Genres (movies)
    'genre_action_mov': {'title': 'Action', 'category': 'Genre (Movies)', 'icon': '💥', 'media_type': 'movie', 'description': 'Adrenaline rush.', 'tmdb_params': {'with_genres': '28', 'sort_by': 'popularity.desc'}},
    'genre_adventure_mov': {'title': 'Adventure', 'category': 'Genre (Movies)', 'icon': '🤠', 'media_type': 'movie', 'description': 'Epic journeys.', 'tmdb_params': {'with_genres': '12', 'sort_by': 'popularity.desc'}},
    'genre_animation_mov': {'title': 'Animation', 'category': 'Genre (Movies)', 'icon': '🎨', 'media_type': 'movie', 'description': 'Cartoons & CGI.', 'tmdb_params': {'with_genres': '16', 'sort_by': 'popularity.desc'}},
    'genre_comedy_mov': {'title': 'Comedy', 'category': 'Genre (Movies)', 'icon': '😂', 'media_type': 'movie', 'description': 'Laugh out loud.', 'tmdb_params': {'with_genres': '35', 'sort_by': 'popularity.desc'}},
    'genre_crime_mov': {'title': 'Crime', 'category': 'Genre (Movies)', 'icon': '🚓', 'media_type': 'movie', 'description': 'Gangsters & heists.', 'tmdb_params': {'with_genres': '80', 'sort_by': 'popularity.desc'}},
    'genre_docu_mov': {'title': 'Documentary', 'category': 'Genre (Movies)', 'icon': '🎥', 'media_type': 'movie', 'description': 'Real stories.', 'tmdb_params': {'with_genres': '99', 'sort_by': 'vote_average.desc'}},
    'genre_drama_mov': {'title': 'Drama', 'category': 'Genre (Movies)', 'icon': '🎭', 'media_type': 'movie', 'description': 'Serious stories.', 'tmdb_params': {'with_genres': '18', 'sort_by': 'popularity.desc'}},
    'genre_family_mov': {'title': 'Family', 'category': 'Genre (Movies)', 'icon': '👨‍👩‍👧‍👦', 'media_type': 'movie', 'description': 'For everyone.', 'tmdb_params': {'with_genres': '10751', 'sort_by': 'popularity.desc'}},
    'genre_fantasy_mov': {'title': 'Fantasy', 'category': 'Genre (Movies)', 'icon': '🐉', 'media_type': 'movie', 'description': 'Magic & myth.', 'tmdb_params': {'with_genres': '14', 'sort_by': 'popularity.desc'}},
    'genre_history_mov': {'title': 'History', 'category': 'Genre (Movies)', 'icon': '🏛️', 'media_type': 'movie', 'description': 'Period pieces.', 'tmdb_params': {'with_genres': '36', 'sort_by': 'popularity.desc'}},
    'genre_horror_mov': {'title': 'Horror', 'category': 'Genre (Movies)', 'icon': '👻', 'media_type': 'movie', 'description': 'Scares & thrills.', 'tmdb_params': {'with_genres': '27', 'sort_by': 'popularity.desc'}},
    'genre_music_mov': {'title': 'Music', 'category': 'Genre (Movies)', 'icon': '🎵', 'media_type': 'movie', 'description': 'Biopics & more.', 'tmdb_params': {'with_genres': '10402', 'sort_by': 'popularity.desc'}},
    'genre_mystery_mov': {'title': 'Mystery', 'category': 'Genre (Movies)', 'icon': '🔎', 'media_type': 'movie', 'description': 'Whodunnit?', 'tmdb_params': {'with_genres': '9648', 'sort_by': 'popularity.desc'}},
    'genre_romance_mov': {'title': 'Romance', 'category': 'Genre (Movies)', 'icon': '💕', 'media_type': 'movie', 'description': 'Love stories.', 'tmdb_params': {'with_genres': '10749', 'sort_by': 'popularity.desc'}},
    'genre_scifi_mov': {'title': 'Sci-Fi', 'category': 'Genre (Movies)', 'icon': '👽', 'media_type': 'movie', 'description': 'Future worlds.', 'tmdb_params': {'with_genres': '878', 'sort_by': 'popularity.desc'}},
    'genre_thriller_mov': {'title': 'Thriller', 'category': 'Genre (Movies)', 'icon': '😱', 'media_type': 'movie', 'description': 'Suspense.', 'tmdb_params': {'with_genres': '53', 'sort_by': 'popularity.desc'}},
    'genre_war_mov': {'title': 'War', 'category': 'Genre (Movies)', 'icon': '🪖', 'media_type': 'movie', 'description': 'Conflict.', 'tmdb_params': {'with_genres': '10752', 'sort_by': 'popularity.desc'}},
    'genre_western_mov': {'title': 'Western', 'category': 'Genre (Movies)', 'icon': '🌵', 'media_type': 'movie', 'description': 'Cowboys.', 'tmdb_params': {'with_genres': '37', 'sort_by': 'popularity.desc'}},

    # Genres (TV)
    'genre_action_tv': {'title': 'Action TV', 'category': 'Genre (TV)', 'icon': '🧨', 'media_type': 'tv', 'description': 'High stakes.', 'tmdb_params': {'with_genres': '10759', 'sort_by': 'popularity.desc'}},
    'genre_animation_tv': {'title': 'Animation TV', 'category': 'Genre (TV)', 'icon': '🖌️', 'media_type': 'tv', 'description': 'Cartoons.', 'tmdb_params': {'with_genres': '16', 'sort_by': 'popularity.desc'}},
    'genre_comedy_tv': {'title': 'Comedy TV', 'category': 'Genre (TV)', 'icon': '🤣', 'media_type': 'tv', 'description': 'Sitcoms.', 'tmdb_params': {'with_genres': '35', 'sort_by': 'popularity.desc'}},
    'genre_crime_tv': {'title': 'Crime TV', 'category': 'Genre (TV)', 'icon': '🕵️‍♀️', 'media_type': 'tv', 'description': 'Procedurals.', 'tmdb_params': {'with_genres': '80', 'sort_by': 'popularity.desc'}},
    'genre_docu_tv': {'title': 'Docu-Series', 'category': 'Genre (TV)', 'icon': '🦁', 'media_type': 'tv', 'description': 'Real life.', 'tmdb_params': {'with_genres': '99', 'sort_by': 'popularity.desc'}},
    'genre_drama_tv': {'title': 'Drama TV', 'category': 'Genre (TV)', 'icon': '🎭', 'media_type': 'tv', 'description': 'Serious stories.', 'tmdb_params': {'with_genres': '18', 'sort_by': 'popularity.desc'}},
    'genre_family_tv': {'title': 'Kids & Family', 'category': 'Genre (TV)', 'icon': '🧸', 'media_type': 'tv', 'description': 'Safe for kids.', 'tmdb_params': {'with_genres': '10762', 'sort_by': 'popularity.desc'}},
    'genre_reality_tv': {'title': 'Reality TV', 'category': 'Genre (TV)', 'icon': '🌹', 'media_type': 'tv', 'description': 'Unscripted.', 'tmdb_params': {'with_genres': '10764', 'sort_by': 'popularity.desc'}},
    'genre_scifi_tv': {'title': 'Sci-Fi TV', 'category': 'Genre (TV)', 'icon': '🛸', 'media_type': 'tv', 'description': 'Otherworldly.', 'tmdb_params': {'with_genres': '10765', 'sort_by': 'popularity.desc'}},

    # Content ratings
    'rating_us_pg': {'title': 'Rated PG', 'category': 'Content Ratings', 'icon': '🟡', 'media_type': 'movie', 'description': 'Parental Guidance.', 'tmdb_params': {'certification_country': 'US', 'certification': 'PG', 'sort_by': 'popularity.desc'}},
    'rating_us_r': {'title': 'Rated R', 'category': 'Content Ratings', 'icon': '🔴', 'media_type': 'movie', 'description': 'Restricted.', 'tmdb_params': {'certification_country': 'US', 'certification': 'R', 'sort_by': 'popularity.desc'}},
    'rating_us_tvma': {'title': 'TV-MA', 'category': 'Content Ratings', 'icon': '🔞', 'media_type': 'tv', 'description': 'Mature Audiences.', 'tmdb_params': {'certification_country': 'US', 'certification': 'TV-MA', 'sort_by': 'popularity.desc'}},

    # extra themes & vibes
    'theme_zombies': {'title': 'Zombies', 'category': 'Themes & Vibes', 'icon': '🧟', 'media_type': 'movie', 'description': 'Undead & survival.', 'tmdb_params': {'with_keywords': '12249', 'with_genres': '27', 'sort_by': 'popularity.desc'}},
    'theme_vampires': {'title': 'Vampires', 'category': 'Themes & Vibes', 'icon': '🧛', 'media_type': 'movie', 'description': 'Fangs & folklore.', 'tmdb_params': {'with_keywords': '8487', 'sort_by': 'popularity.desc'}},
    'theme_courtroom': {'title': 'Courtroom Drama', 'category': 'Themes & Vibes', 'icon': '⚖️', 'media_type': 'movie', 'description': 'Trials & verdicts.', 'tmdb_params': {'with_keywords': '9714', 'with_genres': '18', 'sort_by': 'vote_average.desc'}},
    'theme_spy': {'title': 'Spy & Espionage', 'category': 'Themes & Vibes', 'icon': '🕵️', 'media_type': 'movie', 'description': 'Secret agents.', 'tmdb_params': {'with_keywords': '425', 'sort_by': 'popularity.desc'}},
    'theme_superhero': {'title': 'Superhero', 'category': 'Themes & Vibes', 'icon': '🦸', 'media_type': 'movie', 'description': 'Capes & villains.', 'tmdb_params': {'with_keywords': '9717', 'sort_by': 'popularity.desc'}},
    'theme_christmas': {'title': 'Holiday & Christmas', 'category': 'Themes & Vibes', 'icon': '🎄', 'media_type': 'movie', 'description': 'Seasonal cheer.', 'tmdb_params': {'with_keywords': '207317', 'sort_by': 'popularity.desc'}},
    'theme_martial_arts': {'title': 'Martial Arts', 'category': 'Themes & Vibes', 'icon': '🥋', 'media_type': 'movie', 'description': 'Kung fu & action.', 'tmdb_params': {'with_keywords': '3780', 'sort_by': 'vote_average.desc'}},
    'theme_road_movie': {'title': 'Road Movies', 'category': 'Themes & Vibes', 'icon': '🛣️', 'media_type': 'movie', 'description': 'Journeys & escapes.', 'tmdb_params': {'with_keywords': '9715', 'sort_by': 'popularity.desc'}},
    'theme_true_crime_tv': {'title': 'True Crime', 'category': 'Themes & Vibes', 'icon': '📋', 'media_type': 'tv', 'description': 'Real cases.', 'tmdb_params': {'with_genres': '80', 'sort_by': 'popularity.desc'}},

    # more international
    'spanish_cinema': {'title': 'Spanish Language', 'category': 'International & World', 'icon': '🇪🇸', 'media_type': 'movie', 'description': 'Spain & Latin America.', 'tmdb_params': {'with_original_language': 'es', 'sort_by': 'popularity.desc'}},
    'australian_movies': {'title': 'Australian', 'category': 'International & World', 'icon': '🇦🇺', 'media_type': 'movie', 'description': 'Cinema from down under.', 'tmdb_params': {'with_origin_country': 'AU', 'sort_by': 'popularity.desc'}},
    'german_cinema': {'title': 'German', 'category': 'International & World', 'icon': '🇩🇪', 'media_type': 'movie', 'description': 'German film.', 'tmdb_params': {'with_original_language': 'de', 'sort_by': 'popularity.desc'}},
    'british_comedy_tv': {'title': 'British Comedy', 'category': 'International & World', 'icon': '🇬🇧', 'media_type': 'tv', 'description': 'UK sitcoms & comedy.', 'tmdb_params': {'with_origin_country': 'GB', 'with_genres': '35', 'sort_by': 'popularity.desc'}},

    # more studios & networks
    'studio_marvel': {'title': 'Marvel', 'category': 'Studios & Networks', 'icon': '🦸', 'media_type': 'movie', 'description': 'MCU & more.', 'tmdb_params': {'with_companies': '420', 'sort_by': 'release_date.desc'}},
    'studio_disney_animation': {'title': 'Disney Animation', 'category': 'Studios & Networks', 'icon': '🏰', 'media_type': 'movie', 'description': 'Classic & new.', 'tmdb_params': {'with_companies': '2', 'sort_by': 'popularity.desc'}},
    'network_bbc': {'title': 'BBC', 'category': 'Studios & Networks', 'icon': '🇬🇧', 'media_type': 'tv', 'description': 'British drama & docs.', 'tmdb_params': {'with_networks': '12', 'sort_by': 'vote_average.desc', 'vote_count.gte': '100'}},

    # more genres / niche
    'genre_romance_tv': {'title': 'Romance TV', 'category': 'Genre (TV)', 'icon': '💕', 'media_type': 'tv', 'description': 'Love stories.', 'tmdb_params': {'with_genres': '10749', 'sort_by': 'popularity.desc'}},
    # tv has no Horror genre. use Drama + horror keyword (narrows to serious horror, not cartoons) and exclude Animation/Kids/Family
    'genre_horror_tv': {'title': 'Horror TV', 'category': 'Genre (TV)', 'icon': '👻', 'media_type': 'tv', 'description': 'Spooky & supernatural.', 'tmdb_params': {'with_genres': '18', 'with_keywords': '315058', 'without_genres': '16|10762|10751', 'vote_count.gte': '300', 'vote_average.gte': '6.5', 'sort_by': 'vote_average.desc'}},
    'genre_mystery_tv': {'title': 'Mystery TV', 'category': 'Genre (TV)', 'icon': '🔍', 'media_type': 'tv', 'description': 'Whodunnits.', 'tmdb_params': {'with_genres': '9648', 'sort_by': 'popularity.desc'}},
    'new_releases_mov': {'title': 'New Releases', 'category': 'Decades', 'icon': '🆕', 'media_type': 'movie', 'description': 'This year.', 'tmdb_params': {'primary_release_date.gte': '2025-01-01', 'sort_by': 'popularity.desc'}},
    'best_rated_mov': {'title': 'Best Rated', 'category': 'Awards & Acclaim', 'icon': '⭐', 'media_type': 'movie', 'description': 'Top rated ever.', 'tmdb_params': {'vote_average.gte': '8.0', 'vote_count.gte': '2000', 'sort_by': 'vote_average.desc'}},

    # tv decades, more themes, networks, international, genres

    # TV Decades (first_air_date)
    'tv_90s': {'title': 'The 1990s (TV)', 'category': 'Decades', 'icon': '📺', 'media_type': 'tv', 'description': 'Classic 90s shows.', 'tmdb_params': {'first_air_date.gte': '1990-01-01', 'first_air_date.lte': '1999-12-31', 'sort_by': 'popularity.desc'}},
    'tv_2000s': {'title': 'The 2000s (TV)', 'category': 'Decades', 'icon': '💿', 'media_type': 'tv', 'description': 'Early 2000s TV.', 'tmdb_params': {'first_air_date.gte': '2000-01-01', 'first_air_date.lte': '2009-12-31', 'sort_by': 'popularity.desc'}},
    'tv_2010s': {'title': 'The 2010s (TV)', 'category': 'Decades', 'icon': '📱', 'media_type': 'tv', 'description': 'Peak TV era.', 'tmdb_params': {'first_air_date.gte': '2010-01-01', 'first_air_date.lte': '2019-12-31', 'sort_by': 'popularity.desc'}},
    'tv_2020s': {'title': 'The 2020s (TV)', 'category': 'Decades', 'icon': '🆕', 'media_type': 'tv', 'description': 'Current hits.', 'tmdb_params': {'first_air_date.gte': '2020-01-01', 'sort_by': 'popularity.desc'}},
    'new_releases_tv': {'title': 'New TV', 'category': 'Decades', 'icon': '🆕', 'media_type': 'tv', 'description': 'This year.', 'tmdb_params': {'first_air_date.gte': '2025-01-01', 'sort_by': 'popularity.desc'}},

    # More themes (movies)
    'theme_noir': {'title': 'Film Noir', 'category': 'Themes & Vibes', 'icon': '🎩', 'media_type': 'movie', 'description': 'Shadow & style.', 'tmdb_params': {'with_keywords': '3795', 'sort_by': 'vote_average.desc', 'vote_count.gte': '100'}},
    'theme_revenge': {'title': 'Revenge', 'category': 'Themes & Vibes', 'icon': '⚔️', 'media_type': 'movie', 'description': 'Payback.', 'tmdb_params': {'with_keywords': '424', 'sort_by': 'popularity.desc'}},
    'theme_prison': {'title': 'Prison', 'category': 'Themes & Vibes', 'icon': '🔒', 'media_type': 'movie', 'description': 'Behind bars.', 'tmdb_params': {'with_keywords': '10489', 'sort_by': 'popularity.desc'}},
    'theme_wedding': {'title': 'Wedding', 'category': 'Themes & Vibes', 'icon': '💒', 'media_type': 'movie', 'description': 'I dos & drama.', 'tmdb_params': {'with_keywords': '265710', 'sort_by': 'popularity.desc'}},
    'theme_biopic': {'title': 'Biopics', 'category': 'Themes & Vibes', 'icon': '📜', 'media_type': 'movie', 'description': 'Based on real lives.', 'tmdb_params': {'with_keywords': '258', 'sort_by': 'vote_average.desc', 'vote_count.gte': '200'}},
    'theme_halloween': {'title': 'Halloween & Horror', 'category': 'Themes & Vibes', 'icon': '🎃', 'media_type': 'movie', 'description': 'Spooky season.', 'tmdb_params': {'with_genres': '27', 'sort_by': 'popularity.desc'}},
    'theme_valentine': {'title': 'Rom-Com & Valentine', 'category': 'Themes & Vibes', 'icon': '💝', 'media_type': 'movie', 'description': 'Love & laughs.', 'tmdb_params': {'with_genres': '10749', 'sort_by': 'popularity.desc'}},
    'theme_apocalypse': {'title': 'Apocalypse & Survival', 'category': 'Themes & Vibes', 'icon': '🌍', 'media_type': 'movie', 'description': 'End of the world.', 'tmdb_params': {'with_keywords': '4414', 'sort_by': 'popularity.desc'}},
    'theme_cyberpunk': {'title': 'Cyberpunk & Tech', 'category': 'Themes & Vibes', 'icon': '🤖', 'media_type': 'movie', 'description': 'High tech, low life.', 'tmdb_params': {'with_keywords': '818', 'with_genres': '878', 'sort_by': 'vote_average.desc'}},
    'theme_war_movies': {'title': 'War & Military', 'category': 'Themes & Vibes', 'icon': '🪖', 'media_type': 'movie', 'description': 'Conflict & courage.', 'tmdb_params': {'with_genres': '10752', 'sort_by': 'popularity.desc'}},

    # More themes (TV)
    'theme_anthology_tv': {'title': 'Anthology Series', 'category': 'Themes & Vibes', 'icon': '📚', 'media_type': 'tv', 'description': 'New story each season.', 'tmdb_params': {'with_keywords': '11162', 'sort_by': 'vote_average.desc', 'vote_count.gte': '50'}},
    'theme_sitcom_tv': {'title': 'Sitcoms', 'category': 'Themes & Vibes', 'icon': '😂', 'media_type': 'tv', 'description': 'Laugh tracks & life.', 'tmdb_params': {'with_genres': '35', 'sort_by': 'popularity.desc'}},
    'theme_sci_fi_tv': {'title': 'Sci-Fi & Fantasy TV', 'category': 'Themes & Vibes', 'icon': '🛸', 'media_type': 'tv', 'description': 'Space & magic.', 'tmdb_params': {'with_genres': '10765', 'sort_by': 'popularity.desc'}},
    'theme_cop_procedural_tv': {'title': 'Cop & Procedural', 'category': 'Themes & Vibes', 'icon': '🚔', 'media_type': 'tv', 'description': 'Case of the week.', 'tmdb_params': {'with_genres': '80', 'sort_by': 'popularity.desc'}},

    # More international (movies + TV)
    'japanese_cinema': {'title': 'Japanese Cinema', 'category': 'International & World', 'icon': '🇯🇵', 'media_type': 'movie', 'description': 'Japan film.', 'tmdb_params': {'with_original_language': 'ja', 'sort_by': 'popularity.desc'}},
    'italian_cinema': {'title': 'Italian Cinema', 'category': 'International & World', 'icon': '🇮🇹', 'media_type': 'movie', 'description': 'Neorealism & more.', 'tmdb_params': {'with_original_language': 'it', 'sort_by': 'popularity.desc'}},
    'mexican_cinema': {'title': 'Mexican Cinema', 'category': 'International & World', 'icon': '🇲🇽', 'media_type': 'movie', 'description': 'Mexico film.', 'tmdb_params': {'with_origin_country': 'MX', 'sort_by': 'popularity.desc'}},
    'anime_tv': {'title': 'Anime (TV)', 'category': 'International & World', 'icon': '🗾', 'media_type': 'tv', 'description': 'Japanese animation.', 'tmdb_params': {'with_original_language': 'ja', 'with_genres': '16', 'sort_by': 'popularity.desc'}},
    'spanish_tv': {'title': 'Spanish & Latin TV', 'category': 'International & World', 'icon': '🇪🇸', 'media_type': 'tv', 'description': 'Telenovelas & drama.', 'tmdb_params': {'with_original_language': 'es', 'sort_by': 'popularity.desc'}},
    'australian_tv': {'title': 'Australian TV', 'category': 'International & World', 'icon': '🇦🇺', 'media_type': 'tv', 'description': 'Down under series.', 'tmdb_params': {'with_origin_country': 'AU', 'sort_by': 'popularity.desc'}},
    'canadian_tv': {'title': 'Canadian TV', 'category': 'International & World', 'icon': '🇨🇦', 'media_type': 'tv', 'description': 'Canadian series.', 'tmdb_params': {'with_origin_country': 'CA', 'sort_by': 'popularity.desc'}},

    # More studios & networks (FlixPatrol-style “Networks Top”)
    'studio_dc': {'title': 'DC', 'category': 'Studios & Networks', 'icon': '🦇', 'media_type': 'movie', 'description': 'DC Comics films.', 'tmdb_params': {'with_companies': '174', 'sort_by': 'release_date.desc'}},
    'studio_universal': {'title': 'Universal', 'category': 'Studios & Networks', 'icon': '🌐', 'media_type': 'movie', 'description': 'Universal Pictures.', 'tmdb_params': {'with_companies': '33', 'sort_by': 'popularity.desc'}},
    'studio_warner': {'title': 'Warner Bros', 'category': 'Studios & Networks', 'icon': '🎬', 'media_type': 'movie', 'description': 'WB films.', 'tmdb_params': {'with_companies': '174', 'sort_by': 'popularity.desc'}},
    'studio_paramount': {'title': 'Paramount', 'category': 'Studios & Networks', 'icon': '🏔️', 'media_type': 'movie', 'description': 'Paramount Pictures.', 'tmdb_params': {'with_companies': '4', 'sort_by': 'popularity.desc'}},
    'network_hulu': {'title': 'Hulu Originals', 'category': 'Studios & Networks', 'icon': '🟢', 'media_type': 'tv', 'description': 'Hulu series.', 'tmdb_params': {'with_networks': '453', 'sort_by': 'popularity.desc'}},
    'network_disney_plus': {'title': 'Disney+ Originals', 'category': 'Studios & Networks', 'icon': '✨', 'media_type': 'tv', 'description': 'Disney+ series.', 'tmdb_params': {'with_networks': '2739', 'sort_by': 'popularity.desc'}},
    'network_prime': {'title': 'Prime Video', 'category': 'Studios & Networks', 'icon': '📦', 'media_type': 'tv', 'description': 'Amazon Originals.', 'tmdb_params': {'with_networks': '1024', 'sort_by': 'popularity.desc'}},
    'network_fx': {'title': 'FX', 'category': 'Studios & Networks', 'icon': '📺', 'media_type': 'tv', 'description': 'FX series.', 'tmdb_params': {'with_networks': '3186', 'sort_by': 'vote_average.desc', 'vote_count.gte': '100'}},
    'network_amc': {'title': 'AMC', 'category': 'Studios & Networks', 'icon': '🧟', 'media_type': 'tv', 'description': 'AMC drama.', 'tmdb_params': {'with_networks': '88', 'sort_by': 'vote_average.desc', 'vote_count.gte': '100'}},
    'network_showtime': {'title': 'Showtime', 'category': 'Studios & Networks', 'icon': '📺', 'media_type': 'tv', 'description': 'Showtime series.', 'tmdb_params': {'with_networks': '67', 'sort_by': 'popularity.desc'}},
    'network_cw': {'title': 'The CW', 'category': 'Studios & Networks', 'icon': '📺', 'media_type': 'tv', 'description': 'CW drama & genre.', 'tmdb_params': {'with_networks': '71', 'sort_by': 'popularity.desc'}},

    # More genres (TV) - Fantasy, Thriller, Adventure
    'genre_fantasy_tv': {'title': 'Fantasy TV', 'category': 'Genre (TV)', 'icon': '🐉', 'media_type': 'tv', 'description': 'Magic & myth.', 'tmdb_params': {'with_genres': '10765', 'sort_by': 'popularity.desc'}},
    'genre_thriller_tv': {'title': 'Thriller TV', 'category': 'Genre (TV)', 'icon': '😱', 'media_type': 'tv', 'description': 'Suspense & mystery.', 'tmdb_params': {'with_genres': '9648', 'sort_by': 'popularity.desc'}},
    'genre_adventure_tv': {'title': 'Adventure TV', 'category': 'Genre (TV)', 'icon': '🗺️', 'media_type': 'tv', 'description': 'Action & adventure.', 'tmdb_params': {'with_genres': '10759', 'sort_by': 'popularity.desc'}},
    'genre_history_tv': {'title': 'History & Period TV', 'category': 'Genre (TV)', 'icon': '🏛️', 'media_type': 'tv', 'description': 'Period drama.', 'tmdb_params': {'with_genres': '36', 'sort_by': 'popularity.desc'}},
    'genre_war_tv': {'title': 'War & Military TV', 'category': 'Genre (TV)', 'icon': '🪖', 'media_type': 'tv', 'description': 'Conflict on screen.', 'tmdb_params': {'with_genres': '10768', 'sort_by': 'popularity.desc'}},
    'best_rated_tv': {'title': 'Best Rated TV', 'category': 'Awards & Acclaim', 'icon': '⭐', 'media_type': 'tv', 'description': 'Top rated ever.', 'tmdb_params': {'vote_average.gte': '8.0', 'vote_count.gte': '500', 'sort_by': 'vote_average.desc'}},

    # Content ratings (more)
    'rating_us_pg13': {'title': 'Rated PG-13', 'category': 'Content Ratings', 'icon': '🟠', 'media_type': 'movie', 'description': 'Teens and up.', 'tmdb_params': {'certification_country': 'US', 'certification': 'PG-13', 'sort_by': 'popularity.desc'}},
    'rating_us_g': {'title': 'Rated G', 'category': 'Content Ratings', 'icon': '🟢', 'media_type': 'movie', 'description': 'All ages.', 'tmdb_params': {'certification_country': 'US', 'certification': 'G', 'sort_by': 'popularity.desc'}},
    'rating_us_tvpg': {'title': 'TV-PG', 'category': 'Content Ratings', 'icon': '🟡', 'media_type': 'tv', 'description': 'Parental guidance.', 'tmdb_params': {'certification_country': 'US', 'certification': 'TV-PG', 'sort_by': 'popularity.desc'}},
    'rating_us_tv14': {'title': 'TV-14', 'category': 'Content Ratings', 'icon': '🟠', 'media_type': 'tv', 'description': 'Ages 14+.', 'tmdb_params': {'certification_country': 'US', 'certification': 'TV-14', 'sort_by': 'popularity.desc'}},

    # Documentary subcategories
    'docu_nature_mov': {'title': 'Nature Docs', 'category': 'Genre (Movies)', 'icon': '🦁', 'media_type': 'movie', 'description': 'Wildlife & planet.', 'tmdb_params': {'with_genres': '99', 'with_keywords': '25836', 'sort_by': 'vote_average.desc'}},
    'docu_crime_mov': {'title': 'True Crime Docs', 'category': 'Genre (Movies)', 'icon': '📋', 'media_type': 'movie', 'description': 'Real crime stories.', 'tmdb_params': {'with_genres': '99', 'with_keywords': '9714', 'sort_by': 'popularity.desc'}},
    'docu_music_mov': {'title': 'Music Docs', 'category': 'Genre (Movies)', 'icon': '🎵', 'media_type': 'movie', 'description': 'Bands & musicians.', 'tmdb_params': {'with_genres': '99', 'sort_by': 'popularity.desc'}},
}