from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.vod.provider_metadata import project_provider_metadata


def relation(
    relation_id,
    *,
    category,
    priority,
    basic=None,
    detailed=None,
    account="Provider",
):
    return SimpleNamespace(
        id=relation_id,
        m3u_account_id=priority + 100,
        category_id=relation_id + 200,
        m3u_account=SimpleNamespace(name=account, priority=priority),
        category=SimpleNamespace(name=category),
        custom_properties={
            "basic_data": basic or {},
            **({"detailed_info": detailed} if detailed else {}),
        },
    )


class ProviderMetadataProjectionTests(SimpleTestCase):
    def test_preferred_language_category_wins_then_missing_fields_fall_back(self):
        english = relation(
            1,
            category="EN | Movies",
            priority=100,
            basic={
                "name": "English title",
                "plot": "English description",
                "trailer": "english-trailer",
                "cast": ["Actor One", "Actor Two"],
            },
            account="English provider",
        )
        german = relation(
            2,
            category="┃DE┃ FILME",
            priority=10,
            basic={
                "name": "Deutscher Titel",
                "plot": "Deutsche Beschreibung",
            },
            account="German provider",
        )

        projection = project_provider_metadata(
            [english, german],
            content_type="movie",
            preferred_aliases={"de", "ger", "deutsch"},
        )

        self.assertEqual(
            projection["scalar"]["description"], "Deutsche Beschreibung"
        )
        self.assertEqual(projection["scalar"]["display_name"], "Deutscher Titel")
        self.assertEqual(
            projection["custom"]["youtube_trailer"], "english-trailer"
        )
        self.assertEqual(
            projection["custom"]["actors"], "Actor One, Actor Two"
        )
        self.assertEqual(
            projection["sources"]["description"]["relation_id"], 2
        )
        self.assertEqual(
            projection["sources"]["youtube_trailer"]["relation_id"], 1
        )

    def test_detailed_payload_wins_within_the_same_source(self):
        source = relation(
            3,
            category="DE - Filme",
            priority=10,
            basic={"plot": "List plot", "duration": "90"},
            detailed={"plot": "Detailed plot", "director": "Director"},
        )

        projection = project_provider_metadata(
            [source], content_type="movie", preferred_aliases={"de"}
        )

        self.assertEqual(projection["scalar"]["description"], "Detailed plot")
        self.assertEqual(projection["scalar"]["duration_secs"], 90 * 60)
        self.assertEqual(projection["custom"]["director"], "Director")
