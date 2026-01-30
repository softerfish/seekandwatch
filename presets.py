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
    'theme_miniseries': {'title': 'Miniseries', 'category': 'Themes & Vibes', 'icon': '📚', 'media_type': 'tv', 'description': 'Limited series.', 'tmdb_params': {'with_keywords': '210024', 'sort_by': 'vote_average.desc', 'vote_count.gte': '100'}},

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
    'theme_true_crime_tv': {'title': 'True Crime', 'category': 'Themes & Vibes', 'icon': '📋', 'media_type': 'tv', 'description': 'Real cases.', 'tmdb_params': {'with_genres': '80', 'with_keywords': '210024', 'sort_by': 'popularity.desc'}},

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
    'genre_horror_tv': {'title': 'Horror TV', 'category': 'Genre (TV)', 'icon': '👻', 'media_type': 'tv', 'description': 'Spooky & supernatural.', 'tmdb_params': {'with_genres': '10765', 'sort_by': 'popularity.desc'}},
    'genre_mystery_tv': {'title': 'Mystery TV', 'category': 'Genre (TV)', 'icon': '🔍', 'media_type': 'tv', 'description': 'Whodunnits.', 'tmdb_params': {'with_genres': '9648', 'sort_by': 'popularity.desc'}},
    'new_releases_mov': {'title': 'New Releases', 'category': 'Decades', 'icon': '🆕', 'media_type': 'movie', 'description': 'This year.', 'tmdb_params': {'primary_release_date.gte': '2025-01-01', 'sort_by': 'popularity.desc'}},
    'best_rated_mov': {'title': 'Best Rated', 'category': 'Awards & Acclaim', 'icon': '⭐', 'media_type': 'movie', 'description': 'Top rated ever.', 'tmdb_params': {'vote_average.gte': '8.0', 'vote_count.gte': '2000', 'sort_by': 'vote_average.desc'}},
}