from flask import Flask, render_template, redirect, url_for, jsonify, session, request, send_from_directory
from flask_paginate import Pagination, get_page_args
import mysqlDB as msq
import secrets
from datetime import datetime, timedelta
import requests
import random
import re
import os
from flask_session import Session
import logging

app = Flask(__name__)
msq.init_app(app)

# Klucz tajny do szyfrowania sesji
app.config['SECRET_KEY'] = secrets.token_hex(16)

# Ustawienia dla Flask-Session
app.config['SESSION_TYPE'] = 'filesystem'  # Można użyć np. 'redis', 'sqlalchemy'
app.config['SESSION_PERMANENT'] = True  # Sesja ma być permanentna
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)  # Czas wygaśnięcia sesji (10 minut)

# Ustawienie ilości elementów na stronę (nie dotyczy sesji)
app.config['PER_PAGE'] = 6

# Inicjalizacja obsługi sesji
Session(app)

def getLangText(text, dest="en", source="pl"):
    if not text:
        return text
    # bezpiecznik: nie tłumacz "ścian"
    if len(text) > 8000:
        return text
    try:
        r = requests.post(
            "http://127.0.0.1:5055/translate",
            json={"text": text, "source": source, "target": dest, "format": "text"},
            timeout=(2, 8),
        )
        r.raise_for_status()
        return r.json().get("text", text)
    except Exception as e:
        print(f"Exception Error: {e}")
        return text

def format_date(date_input, pl=True):
    ang_pol = {
        'January': 'styczeń',
        'February': 'luty',
        'March': 'marzec',
        'April': 'kwiecień',
        'May': 'maj',
        'June': 'czerwiec',
        'July': 'lipiec',
        'August': 'sierpień',
        'September': 'wrzesień',
        'October': 'październik',
        'November': 'listopad',
        'December': 'grudzień'
    }
    # Sprawdzenie czy data_input jest instancją stringa; jeśli nie, zakładamy, że to datetime
    if isinstance(date_input, str):
        date_object = datetime.strptime(date_input, '%Y-%m-%d %H:%M:%S')
    else:
        # Jeśli date_input jest już obiektem datetime, używamy go bezpośrednio
        date_object = date_input

    formatted_date = date_object.strftime('%d %B %Y')
    if pl:
        for en, pl in ang_pol.items():
            formatted_date = formatted_date.replace(en, pl)

    return formatted_date


#  Funkcja pobiera dane z bazy danych 
def take_data_where_ID(key, table, id_name, ID):
    dump_key = msq.connect_to_database(f'SELECT {key} FROM {table} WHERE {id_name} = {ID};')
    return dump_key

def take_data_table(key, table):
    dump_key = msq.connect_to_database(f'SELECT {key} FROM {table};')
    return dump_key

def generator_subsDataDB():
    subsData = []
    took_subsD = take_data_table('*', 'newsletter')
    for data in took_subsD:
        if data[4] != 1: continue
        ID = data[0]
        theme = {
            'id': ID, 
            'email':data[2],
            'name':data[1], 
            'status': str(data[4]), 
            }
        subsData.append(theme)
    return subsData

def _blog_rows(limit=None, post_id=None, detailed=False, offset=0, cards=False, post_ids=None):
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    if offset and limit is None:
        raise ValueError('offset requires a limit')
    columns = [
        ('p.ID', 'post_id'), ('c.ID', 'id'), ('c.TITLE', 'title'),
        ('c.HIGHLIGHTS', 'highlight'), ('c.HEADER_FOTO', 'mainFoto'),
        ('c.CATEGORY', 'category'), ('c.DATE_TIME', 'data'),
        ('a.NAME_AUTHOR', 'author'),
    ]
    if cards and not detailed:
        columns += [('c.TAGS', 'tags'), ('c.CONTENT_FOTO', 'contentFoto')]
    if detailed:
        columns += [
            ('c.CONTENT_MAIN', 'introduction'), ('c.CONTENT_FOTO', 'contentFoto'),
            ('c.BULLETS', 'additionalList'), ('c.TAGS', 'tags'),
            ('a.ABOUT_AUTHOR', 'author_about'), ('a.AVATAR_AUTHOR', 'author_avatar'),
            ('a.FACEBOOK', 'author_facebook'), ('a.TWITER_X', 'author_twitter'),
            ('a.INSTAGRAM', 'author_instagram'),
        ]
    query = 'SELECT ' + ', '.join(column for column, _ in columns)
    query += """
        FROM blog_posts p
        LEFT JOIN contents c ON c.ID = p.CONTENT_ID
        LEFT JOIN authors a ON a.ID = p.AUTHOR_ID
    """
    params = []
    if post_id is not None:
        query += ' WHERE p.ID = %s'
        params.append(post_id)
    if post_ids is not None:
        if not post_ids:
            return []
        query += (' AND ' if post_id is not None else ' WHERE ')
        query += 'p.ID IN (' + ', '.join(['%s'] * len(post_ids)) + ')'
        params.extend(post_ids)
    query += ' ORDER BY p.ID DESC'
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError('limit must be a non-negative integer')
        query += ' LIMIT %s'
        params.append(limit)
        if offset:
            query += ' OFFSET %s'
            params.append(offset)
    rows = msq.safe_connect_to_database(query, tuple(params))
    return [dict(zip((key for _, key in columns), row)) for row in rows]


def _blog_theme(row, lang):
    theme = {key: value for key, value in row.items() if key != 'post_id'}
    if lang != 'pl':
        for key in ('title', 'highlight', 'category', 'introduction',
                    'additionalList', 'tags', 'author_about'):
            if key in theme:
                theme[key] = getLangText(theme[key])
    theme['data'] = format_date(theme['data'], lang == 'pl')
    if 'additionalList' in theme:
        bullets = str(theme['additionalList'])
        if lang != 'pl':
            bullets = bullets.replace('#SPLX#', '#splx#')
        theme['additionalList'] = bullets.split('#splx#')
    if 'tags' in theme:
        theme['tags'] = str(theme['tags']).split(', ')
    return theme


def _blog_details(lang='pl', post_id=None):
    rows = _blog_rows(post_id=post_id, detailed=True)
    if not rows:
        return []
    # Fetch comments and their authors once for the whole selected collection.
    query = """
        SELECT com.*, n.CLIENT_NAME, n.CLIENT_EMAIL, n.AVATAR_USER, stats.comment_count
        FROM comments com
        JOIN blog_posts p ON p.ID = com.BLOG_POST_ID
        LEFT JOIN newsletter n ON n.ID = com.AUTHOR_OF_COMMENT_ID
        LEFT JOIN (
            SELECT AUTHOR_OF_COMMENT_ID, COUNT(*) AS comment_count
            FROM comments GROUP BY AUTHOR_OF_COMMENT_ID
        ) stats ON stats.AUTHOR_OF_COMMENT_ID = com.AUTHOR_OF_COMMENT_ID
    """
    params = ()
    if post_id is not None:
        query += ' WHERE p.ID = %s'
        params = (post_id,)
    query += ' ORDER BY com.ID'
    comments = {}
    for com in msq.safe_connect_to_database(query, params):
        post_comments = comments.setdefault(com[1], {})
        post_comments[len(post_comments)] = {
            'id': com[0],
            'message': com[2] if lang == 'pl' else getLangText(com[2]),
            'user': com[-4], 'e-mail': com[-3], 'avatar': com[-2],
            'data-time': format_date(com[4], lang == 'pl'),
        }
        if post_id is not None:
            count = com[-1] or 0
            bonus = 4 if count > 10 else 2 if count > 4 else 1 if count > 1 else 0
            post_comments[len(post_comments) - 1]['user_stars'] = 1 + bool(com[-2]) + bonus
    result = []
    for row in rows:
        theme = _blog_theme(row, lang)
        theme['comments'] = comments.get(row['post_id'], {})
        result.append(theme)
    return result


def generator_daneDBList(lang='pl'):
    return _blog_details(lang)


def generator_daneDBList_short(lang='pl', limit=None, offset=0):
    # Unlimited by default: the home page explicitly requests only three rows.
    return [_blog_theme(row, lang) for row in _blog_rows(limit=limit, offset=offset)]


def _blog_count():
    rows = msq.connect_to_database('SELECT COUNT(*) FROM blog_posts')
    return rows[0][0] if rows else 0


def generator_daneDBList_cetegory():
    took_allPost = msq.connect_to_database('SELECT CATEGORY FROM contents ORDER BY ID DESC;')
    cat_count = {}
    for (category,) in took_allPost:
        cat_count[category] = cat_count.get(category, 0) + 1
    return [f"{cat} ({count})" for cat, count in cat_count.items()], cat_count


def generator_daneDBList_RecentPosts(main_id, amount=3):
    # Preserve the existing random selection of suggested posts.
    rows = msq.safe_connect_to_database(
        'SELECT ID FROM contents WHERE ID != %s ORDER BY ID DESC', (main_id,))
    ids = [row[0] for row in rows]
    return random.sample(ids, min(amount, len(ids)))


def generator_daneDBList_one_post_id(id_post, lang='pl'):
    return _blog_details(lang, post_id=id_post)


def _blog_page(limit, offset, lang='pl'):
    return [_blog_theme(row, lang) for row in _blog_rows(limit=limit, offset=offset, cards=True)]


def _blog_recent_posts(main_id, amount=3, lang='pl'):
    ids = generator_daneDBList_RecentPosts(main_id, amount)
    rows = {row['post_id']: row for row in _blog_rows(post_ids=ids, cards=True)}
    return [_blog_theme(rows[post_id], lang) for post_id in ids if post_id in rows]


def generator_teamDB(lang='pl'):
    took_teamD = take_data_table('*', 'workers_team')
    teamData = []
    for data in took_teamD:
        theme = {
            'ID': int(data[0]),
            'EMPLOYEE_PHOTO': data[1],
            'EMPLOYEE_NAME': data[2],
            'EMPLOYEE_ROLE': data[3] if lang=='pl' else getLangText(data[3]),
            'EMPLOYEE_DEPARTMENT': data[4],
            'PHONE':'' if data[5] is None else data[5],
            'EMAIL': '' if data[6] is None else data[6],
            'FACEBOOK': '' if data[7] is None else data[7],
            'LINKEDIN': '' if data[8] is None else data[8],
            'DATE_TIME': data[9],
            'STATUS': int(data[10])
        }
        # dostosowane dla dmd instalacje
        if data[4] == 'dmd instalacje':
            teamData.append(theme)
    return teamData

def is_valid_phone(phone):
    # Wzorzec dla numeru telefonu: zaczyna się opcjonalnym plusem, po którym następuje 9-15 cyfr
    pattern = re.compile(r'^\+?\d{9,15}$')
    
    if pattern.match(phone):
        return True
    else:
        return False


logFileName = '/home/johndoe/app/dmdinstalacje/logs/access.log'  # 🔁 ZMIENIAJ dla każdej aplikacji

# Konfiguracja loggera
logging.basicConfig(filename=logFileName, level=logging.INFO,
                    format='%(asctime)s - %(message)s', filemode='a')

# Funkcja do logowania informacji o zapytaniu
def log_request():
    ip_address = request.remote_addr
    date_time = datetime.now()
    endpoint = request.endpoint or request.path  # fallback jeśli brak endpointu
    method = request.method

    logging.info(f'IP: {ip_address}, Time: {date_time}, Endpoint: {endpoint}, Method: {method}')

@app.before_request
def before_request_logging():
    log_request()

############################
##      ######           ###
##      ######           ###
##     ####              ###
##     ####              ###
##    ####               ###
##    ####               ###
##   ####                ###
##   ####                ###
#####                    ###
#####                    ###
##   ####                ###
##   ####                ###
##    ####               ###
##    ####               ###
##     ####              ###
##     ####              ###
##      ######           ###
##      ######           ###
############################



@app.template_filter('smart_truncate')
def smart_truncate(content, length=400):
    if len(content) <= length:
        return content
    else:
        # Znajdujemy miejsce, gdzie jest koniec pełnego słowa, nie przekraczając maksymalnej długości
        truncated_content = content[:length].rsplit(' ', 1)[0]
        return f"{truncated_content}..."


@app.route('/')
def index():
    session['page'] = 'index'
    pageTitle = 'Strona Główna'

    if f'TEAM-ALL' not in session:
        team_list = generator_teamDB()
        session[f'TEAM-ALL'] = team_list
    else:
        team_list = session[f'TEAM-ALL']

    treeListTeam = []
    for i, member in enumerate(team_list):
        if  i < 3: treeListTeam.append(member)
       
    if f'BLOG-SHORT' not in session:
        blog_post = generator_daneDBList_short(limit=3)
        session[f'BLOG-SHORT'] = blog_post
    else:
        blog_post = session[f'BLOG-SHORT']
    
    blog_post_three = []
    for i, member in enumerate(blog_post):
        if  i < 3: blog_post_three.append(member)


    return render_template(
        f'index.html',
        pageTitle=pageTitle,
        blog_post_three=blog_post_three,
        treeListTeam=treeListTeam
        )

@app.route('/uslugi')
def uslugi():
    session['page'] = 'Usługi'
    pageTitle = 'Usługi'

    return render_template(
        f'uslugi.html',
        pageTitle=pageTitle
        )

@app.route('/usluga-fotowoltaika')
def uslugaFotowoltaika():
    session['page'] = 'Fotowoltaika'
    pageTitle = 'Fotowoltaika'

    return render_template(
        f'usluga-fotowoltaika.html',
        pageTitle=pageTitle
        )

@app.route('/usluga-pompy-ciepla')
def uslugaPompyCiepla():
    session['page'] = 'Pompy Ciepła'
    pageTitle = 'Pompy Ciepła'

    return render_template(
        'usluga-pompy-ciepla.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-rekuperacja')
def uslugaRekuperacja():
    session['page'] = 'Rekuperacja'
    pageTitle = 'Rekuperacja'

    return render_template(
        'usluga-rekuperacja.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-wentylacja-klimatyzacja')
def uslugaWentylacjaKlimatyzacja():
    session['page'] = 'Wentylacja i Klimatyzacja'
    pageTitle = 'Wentylacja i Klimatyzacja'

    return render_template(
        'usluga-wentylacja-klimatyzacja.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-ogrzewanie-podlogowe')
def uslugaOgrzewaniePodlogowe():
    session['page'] = 'Ogrzewanie Podłogowe'
    pageTitle = 'Ogrzewanie Podłogowe'

    return render_template(
        'usluga-ogrzewanie-podlogowe.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-instalacje-elektryczne')
def uslugaInstalacjeElektryczne():
    session['page'] = 'Instalacje Elektryczne'
    pageTitle = 'Instalacje Elektryczne'

    return render_template(
        'usluga-instalacje-elektryczne.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-instalacje-gazowe')
def uslugaInstalacjeGazowe():
    session['page'] = 'Instalacje Gazowe'
    pageTitle = 'Instalacje Gazowe'

    return render_template(
        'usluga-instalacje-gazowe.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-instalacje-grzewcze')
def uslugaInstalacjeGrzewcze():
    session['page'] = 'Instalacje Grzewcze'
    pageTitle = 'Instalacje Grzewcze'

    return render_template(
        'usluga-instalacje-grzewcze.html',
        pageTitle=pageTitle
    )

@app.route('/usluga-instalacje-wodno-kanalizacyjne')
def uslugaInstalacjeWodnoKanalizacyjne():
    session['page'] = 'Instalacje Wodno-Kanalizacyjne'
    pageTitle = 'Instalacje Wodno-Kanalizacyjne'

    return render_template(
        'usluga-instalacje-wodno-kanalizacyjne.html',
        pageTitle=pageTitle
    )


@app.route('/o-nas')
def oNas():
    session['page'] = 'O Nas'
    pageTitle = 'O Nas'

    return render_template(
        f'o-nas.html',
        pageTitle=pageTitle
        )

@app.route('/kontakt')
def kontakt():
    session['page'] = 'kontakt'
    pageTitle = 'kontakt'

    nazwa_oferty = request.args.get('settitle', '')


    return render_template(
        f'kontakt.html',
        pageTitle=pageTitle,
        nazwa_oferty=nazwa_oferty
        )

@app.route('/my-zespol')
def myZespol():
    session['page'] = 'myZespol'
    pageTitle = 'Zespół'

    if f'TEAM-ALL' not in session:
        team_list = generator_teamDB()
        session[f'TEAM-ALL'] = team_list
    else:
        team_list = session[f'TEAM-ALL']

    fullListTeam = []
    for i, member in enumerate(team_list):
       fullListTeam.append(member)
    
    return render_template(
        f'my-zespol.html',
        pageTitle=pageTitle,
        fullListTeam=fullListTeam
        )

@app.route('/blog')
def blogs():
    session['page'] = 'blogs'
    pageTitle = 'Blog'

    # Discard the old full-blog session cache; fetch only this page from SQL.
    session.pop('blog_post', None)
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    page = max(1, page)
    per_page = max(1, per_page)
    offset = (page - 1) * per_page
    total = _blog_count()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap4')
    posts = _blog_page(per_page, offset)

    cats = generator_daneDBList_cetegory()
    cat_dict = cats[1]
    recentPosts = _blog_recent_posts(0)
    
    # print(posts)
    tag_set = set()
    for post_dict in posts:
        if 'tags' in post_dict:
            for tag in post_dict['tags']:
                tag_set.add(tag)
    tag_list = [str(t).replace('#', '') for t in tag_set]

    return render_template(
        f'blog.html',
        pageTitle=pageTitle,
        cat_dict=cat_dict,
        recentPosts=recentPosts,
        pagination=pagination,
        posts=posts,
        tag_list=tag_list
        )

@app.route('/blog-one', methods=['GET'])
def blogOne():
    session['page'] = 'blogOne'
    
    if 'post' in request.args:
        post_id = request.args.get('post')
        try: post_id_int = int(post_id)
        except ValueError: return redirect(url_for('blogs'))
    else:
        return redirect(url_for(f'blogs'))
    
    choiced = generator_daneDBList_one_post_id(post_id_int)[0]
    choiced['len'] = len(choiced['comments'])
    pageTitle = choiced['title']

    cats = generator_daneDBList_cetegory()
    cat_dict = cats[1]
    recentPosts = _blog_recent_posts(post_id_int)

    return render_template(
        f'blog-one.html',
        pageTitle=pageTitle,
        choiced=choiced,
        cat_dict=cat_dict,
        recentPosts=recentPosts
        )


@app.errorhandler(404)
def page_not_found(e):
    # Tutaj możesz przekierować do dowolnej trasy, którą chcesz wyświetlić jako stronę błędu 404.
    return redirect(url_for(f'index'))


@app.route('/find-by-category', methods=['GET'])
def findByCategory():

    query = request.args.get('category')
    if not query:
        if not 'last_search' in session:
            print('Błąd requesta')
            return redirect(url_for('index'))
        else:
            query = session['last_search']
    else:
        session['last_search'] = query
        
    sqlQuery = """
                SELECT ID FROM contents 
                WHERE CATEGORY LIKE %s 
                ORDER BY ID DESC;
                """
    params = (f'%{query}%', )
    results = msq.safe_connect_to_database(sqlQuery, params)
    pageTitle = f'Wyniki wyszukiwania dla categorii {query}'

    searchResults = []
    for find_id in results:
        post_id = int(find_id[0])
        t_post = generator_daneDBList_one_post_id(post_id)[0]
        theme = {
            'id': t_post['id'],
            'title': t_post['title'],
            'mainFoto': t_post['mainFoto'],
            'introduction': smart_truncate(t_post['introduction'], 200),
            'category': t_post['category'],
            'author': t_post['author'],
            'data': t_post['data']
        }
        searchResults.append(theme)

    found = len(searchResults)

    # Ustawienia paginacji
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    total = len(searchResults)
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap4')

    # Pobierz tylko odpowiednią ilość postów na aktualnej stronie
    posts = searchResults[offset: offset + per_page]


    return render_template(
        "searchBlog.html",
        pageTitle=pageTitle,
        posts=posts,
        found=found,
        pagination=pagination
        )

@app.route('/find-by-tags', methods=['GET'])
def findByTags():

    query = request.args.get('tag')

    if not query:
        if not 'last_search' in session:
            print('Błąd requesta')
            return redirect(url_for('index'))
        else:
            query = session['last_search']
    else:
        session['last_search'] = query

    sqlQuery = """
                SELECT ID FROM contents 
                WHERE TAGS LIKE %s 
                ORDER BY ID DESC;
                """
    params = (f'%#{query}%', )
    results = msq.safe_connect_to_database(sqlQuery, params)
    pageTitle = f'Wyniki wyszukiwania dla tagu {query}'

    searchResults = []
    for find_id in results:
        post_id = int(find_id[0])
        t_post = generator_daneDBList_one_post_id(post_id)[0]
        theme = {
            'id': t_post['id'],
            'title': t_post['title'],
            'mainFoto': t_post['mainFoto'],
            'introduction': smart_truncate(t_post['introduction'], 200),
            'category': t_post['category'],
            'author': t_post['author'],
            'data': t_post['data']
        }
        searchResults.append(theme)

    found = len(searchResults)

    # Ustawienia paginacji
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    total = len(searchResults)
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap4')

    # Pobierz tylko odpowiednią ilość postów na aktualnej stronie
    posts = searchResults[offset: offset + per_page]


    return render_template(
        "searchBlog.html",
        pageTitle=pageTitle,
        posts=posts,
        found=found,
        pagination=pagination,
        query=query
        )


@app.route('/search-post-blog', methods=['GET', 'POST']) #, methods=['GET', 'POST']
def searchBlog():
    if request.method == "POST":
        query = request.form["query"]
        if query == '':
            print('Błąd requesta')
            return redirect(url_for('index'))
        
        session['last_search'] = query
    elif 'last_search' in session:
        query = session['last_search']
    else:
        print('Błąd requesta')
        return redirect(url_for('index'))  # Uwaga: poprawiłem 'f' na 'index'

    sqlQuery = """
                SELECT ID FROM contents 
                WHERE TITLE LIKE %s 
                OR CONTENT_MAIN LIKE %s 
                OR HIGHLIGHTS LIKE %s 
                OR BULLETS LIKE %s 
                ORDER BY ID DESC;
                """
    params = (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%')
    results = msq.safe_connect_to_database(sqlQuery, params)
    pageTitle = f'Wyniki wyszukiwania dla {query}'

    searchResults = []
    for find_id in results:
        post_id = int(find_id[0])
        t_post = generator_daneDBList_one_post_id(post_id)[0]
        theme = {
            'id': t_post['id'],
            'title': t_post['title'],
            'mainFoto': t_post['mainFoto'],
            'introduction': smart_truncate(t_post['introduction'], 200),
            'category': t_post['category'],
            'author': t_post['author'],
            'data': t_post['data']
        }
        searchResults.append(theme)

    found = len(searchResults)

    # Ustawienia paginacji
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    total = len(searchResults)
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap4')

    # Pobierz tylko odpowiednią ilość postów na aktualnej stronie
    posts = searchResults[offset: offset + per_page]


    return render_template(
        "searchBlog.html",
        pageTitle=pageTitle,
        posts=posts,
        found=found,
        pagination=pagination
        )

@app.route('/send-mess-pl', methods=['POST'])
def sendMess():

    if request.method == 'POST':
        form_data = request.json
        CLIENT_NAME = form_data['name']
        CLIENT_SUBJECT = form_data['subject']
        CLIENT_EMAIL = form_data['email']
        CLIENT_MESSAGE = form_data['message']

        if 'condition' not in form_data:
            return jsonify(
                {
                    'success': False, 
                    'message': f'Musisz zaakceptować naszą politykę prywatności!'
                })
        if CLIENT_NAME == '':
            return jsonify(
                {
                    'success': False, 
                    'message': f'Musisz podać swoje Imię i Nazwisko!'
                })
        if CLIENT_SUBJECT == '':
            return jsonify(
                {
                    'success': False, 
                    'message': f'Musisz podać temat wiadomości!'
                })
        if CLIENT_EMAIL == '' or '@' not in CLIENT_EMAIL or '.' not in CLIENT_EMAIL or len(CLIENT_EMAIL) < 7:
            return jsonify(
                {
                    'success': False, 
                    'message': f'Musisz podać adres email!'
                })
        if CLIENT_MESSAGE == '':
            return jsonify(
                {
                    'success': False, 
                    'message': f'Musisz podać treść wiadomości!'
                })

        # --- meta z żądania (Flask/FastAPI) ---
        ref = request.headers.get('Referer')
        ua  = request.headers.get('User-Agent')
        # Host: w Flask jest też request.host; w FastAPI/Starlette z ASGI bywa tylko nagłówek
        host = request.headers.get('Host') or getattr(request, 'host', None)

        # Realne IP z uwzględnieniem proxy/CDN:
        xff = request.headers.get('X-Forwarded-For', '')
        ip_from_xff = xff.split(',')[0].strip() if xff else None
        ip = (request.headers.get('CF-Connecting-IP') or ip_from_xff or request.remote_addr)

        zapytanie_sql = '''
            INSERT INTO contact 
                (CLIENT_NAME, CLIENT_EMAIL, SUBJECT, MESSAGE, DONE, remote_ip, referer, user_agent, source_host) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        '''
        dane = (
            CLIENT_NAME,
            CLIENT_EMAIL,
            CLIENT_SUBJECT,
            CLIENT_MESSAGE,
            1,
            ip,
            ref,
            ua,
            host
        )
    
        if msq.insert_to_database(zapytanie_sql, dane):
            return jsonify(
                {
                    'success': True, 
                    'message': f'Wiadomość została wysłana!'
                })
        else:
            return jsonify(
                {
                    'success': False, 
                    'message': f'Wystąpił problem z wysłaniem Twojej wiadomości, skontaktuj się w inny sposób lub spróbuj później!'
                })

    return redirect(url_for('index'))

@app.route('/ask-phone', methods=['POST'])
def askPhone():
    try:
        form_data = request.json
        CLIENT_PHONE = form_data['phone']

        if CLIENT_PHONE == '' or not is_valid_phone(CLIENT_PHONE):
            return jsonify({
                'success': False,
                'message': 'Musisz podać poprawny numer telefonu!'
            })

        CLIENT_NAME = 'Użytkownik strony DMD Instalacje'
        CLIENT_EMAIL = 'brak@adresu.email'
        CLIENT_SUBJECT = 'Prośba o kontakt ze strony DMD Instalacje'
        CLIENT_MESSAGE = f'Proszę o kontakt {CLIENT_PHONE}'

        # --- meta z żądania (Flask/FastAPI) ---
        ref = request.headers.get('Referer')
        ua  = request.headers.get('User-Agent')
        # Host: w Flask jest też request.host; w FastAPI/Starlette z ASGI bywa tylko nagłówek
        host = request.headers.get('Host') or getattr(request, 'host', None)

        # Realne IP z uwzględnieniem proxy/CDN:
        xff = request.headers.get('X-Forwarded-For', '')
        ip_from_xff = xff.split(',')[0].strip() if xff else None
        ip = (request.headers.get('CF-Connecting-IP') or ip_from_xff or request.remote_addr)

        zapytanie_sql = '''
            INSERT INTO contact 
                (CLIENT_NAME, CLIENT_EMAIL, SUBJECT, MESSAGE, DONE, remote_ip, referer, user_agent, source_host) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        '''
        dane = (
            CLIENT_NAME,
            CLIENT_EMAIL,
            CLIENT_SUBJECT,
            CLIENT_MESSAGE,
            1,
            ip,
            ref,
            ua,
            host
        )

        if msq.insert_to_database(zapytanie_sql, dane):
            return jsonify({
                'success': True,
                'message': 'Numer został wysłany!'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Wystąpił problem z wysłaniem numeru telefonu!'
            })

    except Exception as e:
        # Zaloguj błąd po stronie serwera (opcjonalnie)
        print(f'Błąd: {e}')
        return jsonify({
            'success': False,
            'message': 'Wewnętrzny błąd serwera. Spróbuj ponownie później.'
        }), 500


@app.route('/add-subs-pl', methods=['POST'])
def addSubs():
    subsList = generator_subsDataDB() # pobieranie danych subskrybentów

    if request.method == 'POST':
        form_data = request.json

        SUB_NAME = form_data['Imie']
        SUB_EMAIL = form_data['Email']
        USER_HASH = secrets.token_hex(20)

        allowed = True
        for subscriber in subsList:
            if subscriber['email'] == SUB_EMAIL:
                allowed = False

        if allowed:
            # --- meta z żądania (Flask/FastAPI) ---
            ref = request.headers.get('Referer')
            ua  = request.headers.get('User-Agent')
            host = request.headers.get('Host') or getattr(request, 'host', None)

            # Realne IP z uwzględnieniem proxy/CDN:
            xff = request.headers.get('X-Forwarded-For', '')
            ip_from_xff = xff.split(',')[0].strip() if xff else None
            ip = (request.headers.get('CF-Connecting-IP') or ip_from_xff or request.remote_addr)

            # (opcjonalnie) bardzo prosty anty-bot: wymagaj swojej domeny w referer + niepusty UA
            # if (not ua or not ua.strip()) or (ref and 'dmdbudownictwo.pl' not in ref):
            #     abort(403)

            zapytanie_sql = '''
                INSERT INTO newsletter 
                    (CLIENT_NAME, CLIENT_EMAIL, ACTIVE, USER_HASH, remote_ip, referer, user_agent, source_host) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            '''
            dane = (SUB_NAME, SUB_EMAIL, 0, USER_HASH, ip, ref, ua, host)
            
            if msq.insert_to_database(zapytanie_sql, dane):
                return jsonify(
                    {
                        'success': True, 
                        'message': f'Zgłoszenie nowego subskrybenta zostało wysłane, aktywuj przez email!'
                    })
            else:
                return jsonify(
                {
                    'success': False, 
                    'message': f'Niestety nie udało nam się zarejestrować Twojej subskrypcji z powodu niezidentyfikowanego błędu!'
                })
        else:
            return jsonify(
                {
                    'success': False, 
                    'message': f'Podany adres email jest już zarejestrowany!'
                })
    return redirect(url_for('index'))

@app.route('/add-comm-pl', methods=['POST'])
def addComm():
    subsList = generator_subsDataDB() # pobieranie danych subskrybentów

    if request.method == 'POST':
        form_data = request.json
        # print(form_data)
        SUB_ID = None
        SUB_NAME = form_data['Name']
        SUB_EMAIL = form_data['Email']
        SUB_COMMENT = form_data['Comment']
        POST_ID = form_data['id']
        allowed = False
        for subscriber in subsList:
            if subscriber['email'] == SUB_EMAIL and subscriber['name'] == SUB_NAME and int(subscriber['status']) == 1:
                allowed = True
                SUB_ID = subscriber['id']
                break
        if allowed and SUB_ID:
            # print(form_data)
            zapytanie_sql = '''
                    INSERT INTO comments 
                        (BLOG_POST_ID, COMMENT_CONNTENT, AUTHOR_OF_COMMENT_ID) 
                        VALUES (%s, %s, %s);
                    '''
            dane = (POST_ID, SUB_COMMENT, SUB_ID)
            if msq.insert_to_database(zapytanie_sql, dane):
                return jsonify({'success': True, 'message': f'Post został skomentowany!'})
        else:
            return jsonify({'success': False, 'message': f'Musisz być naszym subskrybentem żeby komentować naszego bloga!'})

    return redirect(url_for('blogs'))

@app.route('/subpage', methods=['GET'])
def subpage():
    session['page'] = 'subpage'
    pageTitle = 'subpage'

    if 'target' in request.args:
        if request.args['target'] in ['polityka', 'zasady', 'pomoc', 'faq']:
            targetPage = request.args['target']
            pageTitle = targetPage
        else: 
            targetPage = "pomoc"
            pageTitle = targetPage
    else:
        targetPage = "pomoc"
        pageTitle = targetPage

    return render_template(
        f'{targetPage}.html',
        pageTitle=pageTitle
        )



if __name__ == '__main__':
    # app.run(debug=True, port=5080)
    app.run(debug=True, host='0.0.0.0', port=5080)