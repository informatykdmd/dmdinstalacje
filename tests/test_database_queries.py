"""Offline regression tests; no application startup or production DB access."""
import ast
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import random
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def load_functions(filename, namespace, predicate=lambda name: True):
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and predicate(node.name)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), filename, 'exec'), namespace)
    return namespace


class BlogQueriesTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE blog_posts (ID INTEGER PRIMARY KEY, CONTENT_ID, AUTHOR_ID);
            CREATE TABLE contents (ID INTEGER PRIMARY KEY, TITLE, HIGHLIGHTS,
                HEADER_FOTO, CATEGORY, DATE_TIME, CONTENT_MAIN, CONTENT_FOTO, BULLETS, TAGS);
            CREATE TABLE authors (ID INTEGER PRIMARY KEY, NAME_AUTHOR, ABOUT_AUTHOR,
                AVATAR_AUTHOR, FACEBOOK, TWITER_X, INSTAGRAM);
            CREATE TABLE newsletter (ID INTEGER PRIMARY KEY, CLIENT_NAME, CLIENT_EMAIL, AVATAR_USER);
            CREATE TABLE comments (ID INTEGER PRIMARY KEY, BLOG_POST_ID,
                COMMENT_CONNTENT, AUTHOR_OF_COMMENT_ID, DATE_TIME);
            INSERT INTO authors VALUES (1, 'Author', 'About', 'avatar', 'fb', 'x', 'ig');
            INSERT INTO newsletter VALUES (1, 'Reader', 'reader@example.com', 'reader.png');
        ''')
        for post_id in range(1, 6):
            self.db.execute('INSERT INTO blog_posts VALUES (?, ?, 1)', (post_id, post_id + 100))
            self.db.execute('INSERT INTO contents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (post_id + 100, f'Title {post_id}', 'Highlight', 'header.png',
                             'Category', '2026-01-02 10:00:00', 'Introduction',
                             'content.png', 'one#splx#two', 'tag1, tag2'))
        for comment_id in range(1, 4):
            self.db.execute('INSERT INTO comments VALUES (?, 5, ?, 1, ?)',
                            (comment_id, f'Comment {comment_id}', '2026-01-03 10:00:00'))
        self.queries = []

        def query(sql, params=()):
            self.queries.append((sql, params))
            return self.db.execute(sql.replace('%s', '?'), params).fetchall()

        self.ns = load_functions('run.py', {
            'msq': SimpleNamespace(safe_connect_to_database=query, connect_to_database=query),
            'datetime': datetime, 'random': random, 'getLangText': lambda text: 'EN:' + text,
        }, lambda name: name.startswith(('_blog', 'generator_daneDBList')) or name == 'format_date')

    def test_home_fetches_only_three_rows_in_one_query(self):
        rows = self.ns['generator_daneDBList_short'](limit=3)
        self.assertEqual([row['id'] for row in rows], [105, 104, 103])
        self.assertEqual(len(self.queries), 1)
        self.assertIn('LIMIT %s', self.queries[0][0])
        self.assertEqual(rows[0], dict(id=105, title='Title 5', highlight='Highlight',
                         mainFoto='header.png', category='Category', data='02 styczeń 2026', author='Author'))
        tree = ast.parse((ROOT / 'run.py').read_text(encoding='utf-8'))
        index = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'index')
        calls = [node for node in ast.walk(index) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'generator_daneDBList_short']
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(arg.arg == 'limit' and arg.value.value == 3 for arg in calls[0].keywords))

    def test_full_blog_is_unlimited_and_comments_are_batched(self):
        rows = self.ns['generator_daneDBList']()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(self.queries), 2)
        self.assertEqual(len(rows[0]['comments']), 3)
        self.assertEqual(rows[0]['comments'][0]['user'], 'Reader')
        self.assertEqual(rows[0]['comments'][0]['e-mail'], 'reader@example.com')
        self.assertEqual(rows[1]['comments'], {})
        self.assertEqual(rows[0]['additionalList'], ['one', 'two'])
        self.assertEqual(rows[0]['tags'], ['tag1', 'tag2'])
        self.assertEqual(rows[0]['author_twitter'], 'x')
        self.assertNotIn('LIMIT', self.queries[0][0])

    def test_short_default_keeps_all_posts(self):
        self.assertEqual(len(self.ns['generator_daneDBList_short']()), 5)

    def render_blog_page(self, page, per_page):
        self.ns.update({
            'app': SimpleNamespace(route=lambda *args: lambda view: view),
            'session': {'blog_post': [{'id': -1}]},
            '_blog_recent_posts': lambda main_id: [],
            'generator_daneDBList_cetegory': lambda: ([], {}),
            'get_page_args': lambda **kwargs: (page, per_page, (page - 1) * per_page),
            'Pagination': lambda **kwargs: SimpleNamespace(**kwargs),
            'render_template': lambda template, **kwargs: kwargs,
        })
        load_functions('run.py', self.ns, lambda name: name == 'blogs')
        return self.ns['blogs']()

    def test_blog_route_paginates_in_sql_and_counts_all_posts(self):
        for page, expected_ids in ((1, [105, 104]), (2, [103, 102]), (3, [101]), (4, [])):
            with self.subTest(page=page):
                self.queries.clear()
                result = self.render_blog_page(page, 2)
                self.assertEqual([post['id'] for post in result['posts']], expected_ids)
                self.assertEqual(result['pagination'].total, 5)
                self.assertEqual(result['pagination'].page, page)
                self.assertEqual(result['pagination'].per_page, 2)
                self.assertEqual(len(self.queries), 2)
                self.assertIn('COUNT(*)', self.queries[0][0])
                self.assertIn('LIMIT %s', self.queries[1][0])
                expected_params = (2,) if page == 1 else (2, (page - 1) * 2)
                self.assertEqual(self.queries[1][1], expected_params)
                self.assertNotIn('comments', self.queries[1][0])
                self.assertEqual(set(result['tag_list']), {'tag1', 'tag2'} if expected_ids else set())
                self.assertNotIn('blog_post', self.ns['session'])

    def test_empty_blog_page(self):
        self.db.execute('DELETE FROM blog_posts')
        result = self.render_blog_page(1, 6)
        self.assertEqual(result['posts'], [])
        self.assertEqual(result['pagination'].total, 0)

    def test_blog_route_normalizes_nonpositive_pagination(self):
        result = self.render_blog_page(-1, 0)
        self.assertEqual(result['pagination'].page, 1)
        self.assertEqual(result['pagination'].per_page, 1)
        self.assertEqual([post['id'] for post in result['posts']], [105])

    def test_invalid_sql_offset_is_rejected(self):
        for offset in (-1, True, '2'):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.ns['_blog_rows'](limit=2, offset=offset)
        with self.assertRaises(ValueError):
            self.ns['_blog_rows'](offset=2)
        self.assertEqual(self.queries, [])

    def test_single_post_filters_both_queries_and_translates(self):
        rows = self.ns['generator_daneDBList_one_post_id'](5, 'en')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'EN:Title 5')
        self.assertEqual(rows[0]['comments'][0]['message'], 'EN:Comment 1')
        self.assertEqual(rows[0]['data'], '02 January 2026')
        self.assertEqual([params for _, params in self.queries], [(5,), (5,)])

    def test_missing_post_does_not_query_comments(self):
        self.assertEqual(self.ns['generator_daneDBList_one_post_id'](999), [])
        self.assertEqual(len(self.queries), 1)



    def test_sidebar_batches_selected_posts_without_comments(self):
        self.ns['generator_daneDBList_RecentPosts'] = lambda main_id, amount: [2, 5]
        rows = self.ns['_blog_recent_posts'](0)
        self.assertEqual([row['id'] for row in rows], [102, 105])
        self.assertEqual(rows[0]['contentFoto'], 'content.png')
        self.assertEqual(rows[0]['highlight'], 'Highlight')
        self.assertEqual(len(self.queries), 1)
        self.assertEqual(self.queries[0][1], (2, 5))
        self.assertNotIn('comments', self.queries[0][0])

    def test_empty_sidebar_does_not_fetch_rows(self):
        self.ns['generator_daneDBList_RecentPosts'] = lambda main_id, amount: []
        self.assertEqual(self.ns['_blog_recent_posts'](0), [])
        self.assertEqual(self.queries, [])

    def test_comment_stars_use_total_activity_across_posts(self):
        for count, bonus in ((1, 0), (2, 1), (4, 1), (5, 2), (10, 2), (11, 4)):
            for avatar in ('reader.png', None):
                with self.subTest(count=count, avatar=avatar):
                    self.db.execute('DELETE FROM comments')
                    self.db.execute('UPDATE newsletter SET AVATAR_USER = ?', (avatar,))
                    for comment_id in range(1, count + 1):
                        self.db.execute('INSERT INTO comments VALUES (?, ?, ?, 1, ?)',
                                        (comment_id, 5 if comment_id == 1 else 4,
                                         'Comment', '2026-01-03 10:00:00'))
                    self.queries.clear()
                    rows = self.ns['generator_daneDBList_one_post_id'](5)
                    self.assertEqual(len(rows[0]['comments']), 1)
                    self.assertEqual(rows[0]['comments'][0]['user_stars'],
                                     1 + bool(avatar) + bonus)
                    self.assertEqual(len(self.queries), 2)


class ConnectionTest(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.with_rows = True
        self.cursor.fetchall.return_value = [(1,)]
        self.connect = Mock(return_value=self.connection)
        self.ns = load_functions('mysqlDB.py', {
            'contextmanager': contextmanager,
            'mysql': SimpleNamespace(connector=SimpleNamespace(connect=self.connect)),
            'g': {}, 'has_request_context': lambda: True,
            'current_app': SimpleNamespace(extensions={'mysqlDB': True}),
            'DB': dict(user='test', **{'pass': 'test'}, host='test', base='test'),
            'handle_error': Mock(),
        })

    def test_reads_reuse_connection_without_commit_and_teardown_closes(self):
        for _ in range(3):
            self.assertEqual(self.ns['connect_to_database']('SELECT 1'), [(1,)])
        self.assertEqual(self.connect.call_count, 1)
        self.connection.commit.assert_not_called()
        self.connection.close.assert_not_called()
        self.assertEqual(self.cursor.close.call_count, 3)
        self.ns['close_database_connections']()
        self.connection.close.assert_called_once()
        self.ns['connect_to_database']('SELECT 1')
        self.assertEqual(self.connect.call_count, 2)

    def test_standalone_and_unregistered_apps_close_immediately(self):
        self.ns['has_request_context'] = lambda: False
        self.ns['connect_to_database']('SELECT 1')
        self.connection.close.assert_called_once()
        self.connection.reset_mock()
        self.ns['has_request_context'] = lambda: True
        self.ns['current_app'].extensions.clear()
        self.ns['connect_to_database']('SELECT 1')
        self.connection.close.assert_called_once()

    def test_writes_commit_and_failures_rollback(self):
        self.cursor.with_rows = False
        self.assertTrue(self.ns['insert_to_database']('INSERT INTO t VALUES (%s)', (1,)))
        self.connection.commit.assert_called_once()
        self.cursor.execute.side_effect = RuntimeError('query failed')
        self.assertFalse(self.ns['insert_to_database']('INSERT INTO t VALUES (%s)', (1,)))
        self.connection.rollback.assert_called_once()
        self.ns['close_database_connections']()
        self.connection.close.assert_called_once()

    def test_failed_connect_returns_empty_without_secondary_error(self):
        self.connect.side_effect = RuntimeError('unavailable')
        self.assertEqual(self.ns['safe_connect_to_database']('SELECT %s', (1,)), [])
        self.ns['handle_error'].assert_called_once()

    def test_failed_read_closes_cursor_and_standalone_connection(self):
        self.ns['has_request_context'] = lambda: False
        self.cursor.execute.side_effect = RuntimeError('query failed')
        self.assertEqual(self.ns['connect_to_database']('SELECT 1'), [])
        self.cursor.close.assert_called_once()
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
