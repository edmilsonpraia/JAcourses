import streamlit as st
import hashlib
import time
import re
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

st.set_page_config(
    layout="wide", 
    page_title="Sistema de Cursos Online", 
    page_icon="🎓"
)

st.markdown("""
<style>
.video-container {
    width: 60%;
    margin: auto;
    padding: 10px;
}
.feedback-container {
    width: 70%;
    margin: auto;
    padding: 15px;
    background-color: #f8f9fa;
    border-radius: 5px;
}
.quiz-container {
    width: 80%;
    margin: auto;
    padding: 20px;
    background-color: #ffffff;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.big-font {
    font-size: 35px !important;
    font-weight: bold;
    text-align: center;
    margin-bottom: 30px;
    color: #1E3D59;
}
.medium-font {
    font-size: 20px !important;
}
.course-header {
    font-size: 24px !important;
    color: #2C3E50;
    margin-bottom: 15px;
}
.lesson-title {
    font-size: 20px !important;
    color: #34495E;
    margin: 10px 0;
}
.stVideo {
    max-width: 1500px !important;
    margin: auto;
}
</style>
""", unsafe_allow_html=True)

DB_CONFIG = {
    'dbname': st.secrets["DB_NAME"],
    'user': st.secrets["DB_USER"],
    'password': st.secrets["DB_PASSWORD"],
    'host': st.secrets["DB_HOST"],
    'port': st.secrets["DB_PORT"],
    'sslmode': 'require'
}

def check_active_sessions(email):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*) as active_sessions
                FROM active_sessions
                WHERE email = %s AND last_activity > NOW() - INTERVAL '30 minutes'
            """, (email,))
            result = cur.fetchone()
            return result['active_sessions'] if result else 0
    except Exception:
        return 0

def log_login_attempt(email, success, ip_address='unknown'):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO login_logs (email, success, ip_address)
                VALUES (%s, %s, %s)
            """, (email, success, ip_address))
            conn.commit()
    except Exception:
        pass

def check_login_attempts(email, ip_address='unknown'):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*) as failed_attempts
                FROM login_logs
                WHERE (email = %s OR ip_address = %s)
                AND success = false
                AND attempt_time > NOW() - INTERVAL '15 minutes'
            """, (email, ip_address))
            result = cur.fetchone()
            return result['failed_attempts'] if result else 0
    except Exception:
        return 0

def manage_session(email, action='create'):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            if action == 'create':
                cur.execute("""
                    INSERT INTO active_sessions (email, last_activity)
                    VALUES (%s, NOW())
                    RETURNING session_id
                """, (email,))
                session_id = cur.fetchone()[0]
                conn.commit()
                return session_id
            elif action == 'update':
                cur.execute("""
                    UPDATE active_sessions
                    SET last_activity = NOW()
                    WHERE email = %s
                """, (email,))
                conn.commit()
            elif action == 'delete':
                cur.execute("""
                    DELETE FROM active_sessions
                    WHERE email = %s
                """, (email,))
                conn.commit()
    except Exception:
        return None

def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {str(e)}")
        return None

def execute_query(query, params=None, fetch=False):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            st.error("Não foi possível estabelecer conexão com o banco de dados")
            return None
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch:
                result = cur.fetchall()
            else:
                result = None
            conn.commit()
            return result
    except Exception as e:
        st.error(f"Erro na execução da query: {str(e)}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return None
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def verify_login(email, password):
    if check_login_attempts(email) >= 5:
        st.error("Muitas tentativas de login. Tente novamente mais tarde.")
        return False, None

    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM users 
                WHERE email = %s AND password = %s
            """, (email, hashed_password))
            user = cur.fetchone()
            
            if user:
                if check_active_sessions(email) >= 2:
                    st.error("Número máximo de sessões ativas atingido")
                    log_login_attempt(email, False)
                    return False, None
                
                cur.execute("""
                    UPDATE users 
                    SET last_login = CURRENT_TIMESTAMP 
                    WHERE email = %s
                """, (email,))
                conn.commit()
                
                manage_session(email, 'create')
                log_login_attempt(email, True)
                return True, user['permissions']
            
            log_login_attempt(email, False)
            return False, None
    except Exception as e:
        st.error(f"Erro ao verificar login: {str(e)}")
        return False, None
    finally:
        if conn:
            conn.close()

def verify_video_access(email, course_id, lesson_number):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT permissions 
                FROM users 
                WHERE email = %s
            """, (email,))
            user = cur.fetchone()
            
            if not user or course_id not in user['permissions']:
                return False
            
            cur.execute("""
                SELECT current_lesson, completed_lessons
                FROM student_progress
                WHERE email = %s AND course_id = %s
            """, (email, course_id))
            progress = cur.fetchone()
            
            if not progress:
                return lesson_number == 1
            
            return lesson_number <= progress['current_lesson']
    except Exception:
        return False

def log_video_view(email, course_id, lesson_number):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO video_views (email, course_id, lesson_number, view_time)
                VALUES (%s, %s, %s, NOW())
            """, (email, course_id, lesson_number))
            conn.commit()
    except Exception:
        pass

def manage_course_access():
    st.markdown('<div class="course-container">', unsafe_allow_html=True)
    st.subheader("🔐 Gerenciar Acesso aos Cursos")
    
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT email, permissions 
                FROM users 
                WHERE email LIKE 'estudante%@email.com'
                ORDER BY email
            """)
            students = cur.fetchall()
            
            cur.execute("SELECT id, name FROM courses ORDER BY name")
            courses = cur.fetchall()
            
            if students and courses:
                student_emails = [student['email'] for student in students]
                selected_student = st.selectbox(
                    "👤 Selecione o Estudante",
                    options=student_emails
                )
                
                current_student = next(s for s in students if s['email'] == selected_student)
                current_permissions = current_student['permissions'] if current_student['permissions'] else []
                
                course_options = {course['name']: course['id'] for course in courses}
                selected_courses = st.multiselect(
                    "📚 Selecione os Cursos",
                    options=list(course_options.keys()),
                    default=[c['name'] for c in courses if c['id'] in current_permissions]
                )
                
                if st.button("💾 Atualizar Acesso"):
                    try:
                        new_permissions = [course_options[name] for name in selected_courses]
                        cur.execute("""
                            UPDATE users 
                            SET permissions = %s 
                            WHERE email = %s
                        """, (new_permissions, selected_student))
                        conn.commit()
                        
                        st.success(f"✅ Acesso atualizado para {selected_student}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao atualizar acesso: {str(e)}")
            else:
                st.warning("⚠️ Não há estudantes ou cursos cadastrados")
    except Exception as e:
        st.error(f"Erro ao carregar dados: {str(e)}")
    st.markdown('</div>', unsafe_allow_html=True)

def get_student_progress(email, course_id):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT current_lesson, completed_lessons 
                FROM student_progress 
                WHERE email = %s AND course_id = %s
            """, (email, course_id))
            return cur.fetchone()
    except Exception as e:
        st.error(f"Erro ao buscar progresso: {str(e)}")
        return None

def update_student_progress(email, course_id, lesson_number):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO student_progress (email, course_id, completed_lessons, current_lesson)
                VALUES (%s, %s, ARRAY[%s], %s)
                ON CONFLICT (email, course_id) DO UPDATE
                SET completed_lessons = array_append(student_progress.completed_lessons, %s),
                    current_lesson = %s + 1
            """, (email, course_id, lesson_number, lesson_number + 1, lesson_number, lesson_number))
            conn.commit()
            manage_session(email, 'update')
            return True
    except Exception as e:
        st.error(f"Erro ao atualizar progresso: {str(e)}")
        return False

def extract_youtube_id(url):
    if not url:
        return None
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def manage_quiz(course_id, lesson_number):
    st.markdown('<div class="quiz-container">', unsafe_allow_html=True)
    st.subheader("📝 Gerenciar Quiz")
    
    current_quiz = get_quiz(course_id, lesson_number)
    if not current_quiz:
        current_quiz = [{"question": "", "answer": "", "question_number": i+1} for i in range(5)]
    
    with st.form(key=f"quiz_form_{course_id}_{lesson_number}"):
        questions = []
        st.write("### Preencha as perguntas e respostas do quiz")
        
        for i in range(5):
            st.write(f"**Questão {i+1}**")
            question = st.text_area(
                "Pergunta:",
                value=current_quiz[i]['question'] if i < len(current_quiz) else "",
                key=f"q_{course_id}_{lesson_number}_{i}",
                height=100
            )
            answer = st.text_input(
                "Resposta:",
                value=current_quiz[i]['answer'] if i < len(current_quiz) else "",
                key=f"a_{course_id}_{lesson_number}_{i}"
            )
            st.markdown("---")
            
            if question and answer:
                questions.append({
                    "question": question.strip(),
                    "answer": answer.strip(),
                    "question_number": i+1
                })
        
        submitted = st.form_submit_button("💾 Salvar Quiz")
        if submitted:
            if len(questions) == 5:
                if save_quiz(course_id, lesson_number, questions):
                    st.success("✅ Quiz salvo com sucesso!")
                    st.rerun()
            else:
                st.error("❌ Todas as 5 perguntas e respostas devem ser preenchidas!")
    st.markdown('</div>', unsafe_allow_html=True)

def get_quiz(course_id, lesson_number):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM quiz 
                WHERE course_id = %s AND lesson_number = %s 
                ORDER BY question_number
            """, (course_id, lesson_number))
            return cur.fetchall()
    except Exception as e:
        st.error(f"Erro ao buscar quiz: {str(e)}")
        return []

def save_quiz(course_id, lesson_number, questions):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM quiz 
                WHERE course_id = %s AND lesson_number = %s
            """, (course_id, lesson_number))
            
            for i, question in enumerate(questions, 1):
                cur.execute("""
                    INSERT INTO quiz (course_id, lesson_number, question_number, question, answer)
                    VALUES (%s, %s, %s, %s, %s)
                """, (course_id, lesson_number, i, question['question'], question['answer']))
            conn.commit()
            return True
    except Exception as e:
        st.error(f"Erro ao salvar quiz: {str(e)}")
        return False

def show_quiz(course_id, lesson_number):
    st.markdown('<div class="quiz-container">', unsafe_allow_html=True)
    st.subheader("📝 Quiz da Aula")
    st.write("⚠️ Você precisa acertar todas as questões para avançar para a próxima aula")
    
    quiz_questions = get_quiz(course_id, lesson_number)
    
    if not quiz_questions:
        st.info("ℹ️ Nenhum quiz disponível para esta aula.")
        return
    
    with st.form(key=f"quiz_form_{course_id}_{lesson_number}"):
        responses = []
        for q in quiz_questions:
            st.write(f"**{q['question_number']}.** {q['question']}")
            answer = st.text_input(
                "Sua resposta:",
                key=f"quiz_answer_{course_id}_{lesson_number}_{q['question_number']}"
            )
            responses.append((answer.strip().lower(), q['answer'].lower()))
        
        submitted = st.form_submit_button("📋 Enviar Respostas")
        if submitted:
            if all(resp[0] for resp in responses):
                correct_answers = sum(1 for resp, ans in responses if resp == ans)
                total_questions = len(quiz_questions)
                
                st.write(f"Resultado: {correct_answers}/{total_questions} questões corretas")
                
                for i, (response, question) in enumerate(zip(responses, quiz_questions)):
                    if response[0] == response[1]:
                        st.success(f"✅ Questão {i+1}: Correta!")
                    else:
                        st.error(f"❌ Questão {i+1}: Incorreta - A resposta correta é '{question['answer']}'")
                
                if correct_answers == total_questions:
                    st.balloons()
                    st.success("🎉 Parabéns! Você completou o quiz com sucesso!")
                    update_student_progress(st.session_state.user_email, course_id, lesson_number)
                    st.rerun()
                else:
                    st.warning("⚠️ Você precisa acertar todas as questões para avançar.")
            else:
                st.warning("⚠️ Por favor, responda todas as questões!")
    st.markdown('</div>', unsafe_allow_html=True)

def get_lesson_likes(course_id, lesson_number):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*) as total_likes
                FROM lesson_likes
                WHERE course_id = %s AND lesson_number = %s
            """, (course_id, lesson_number))
            total_likes = cur.fetchone()['total_likes']
            
            cur.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM lesson_likes
                    WHERE course_id = %s 
                    AND lesson_number = %s 
                    AND email = %s
                ) as has_liked
            """, (course_id, lesson_number, st.session_state.user_email))
            has_liked = cur.fetchone()['has_liked']
            
            return total_likes, has_liked
    except Exception as e:
        st.error(f"Erro ao buscar likes: {str(e)}")
        return 0, False

def toggle_like(course_id, lesson_number, email):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM lesson_likes
                    WHERE course_id = %s 
                    AND lesson_number = %s 
                    AND email = %s
                )
            """, (course_id, lesson_number, email))
            exists = cur.fetchone()[0]
            
            if exists:
                cur.execute("""
                    DELETE FROM lesson_likes
                    WHERE course_id = %s 
                    AND lesson_number = %s 
                    AND email = %s
                """, (course_id, lesson_number, email))
            else:
                cur.execute("""
                    INSERT INTO lesson_likes (course_id, lesson_number, email)
                    VALUES (%s, %s, %s)
                """, (course_id, lesson_number, email))
            conn.commit()
            return not exists
    except Exception as e:
        st.error(f"Erro ao processar like: {str(e)}")
        return False

def get_course_feedback(course_id):
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT f.*, u.email as user_email,
                       TO_CHAR(f.created_at, 'DD/MM/YYYY HH24:MI') as formatted_date
                FROM lesson_feedback f
                JOIN users u ON f.email = u.email
                WHERE f.course_id = %s AND f.lesson_number = 0
                ORDER BY f.created_at DESC
            """, (course_id,))
            return cur.fetchall()
    except Exception as e:
        st.error(f"Erro ao buscar feedbacks: {str(e)}")
        return []

def add_course_feedback(course_id, email, feedback_text):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lesson_feedback (course_id, lesson_number, email, feedback_text)
                VALUES (%s, 0, %s, %s)
            """, (course_id, email, feedback_text))
            conn.commit()
            return True
    except Exception as e:
        st.error(f"Erro ao adicionar feedback: {str(e)}")
        return False

def show_admin_dashboard():
    st.title("🎓 Painel do Administrador")
    
    if st.sidebar.button("🚪 Sair do Sistema"):
        manage_session(st.session_state.user_email, 'delete')
        st.session_state.clear()
        st.rerun()
    
    menu = st.sidebar.radio(
        "Menu Principal",
        ["Cursos", "Adicionar Aula", "Gerenciar Quiz", "Gerenciar Acesso", "Ver Avaliações", "Monitoramento"]
    )
    
    if menu == "Cursos":
        st.header("📚 Gerenciar Cursos")
        
        with st.expander("➕ Adicionar Novo Curso"):
            course_id = st.text_input("ID do Curso (ex: python101)")
            course_name = st.text_input("Nome do Curso")
            course_topics = st.text_area("Tópicos do Curso")
            
            if st.button("💾 Salvar Curso"):
                if course_id and course_name:
                    try:
                        conn = get_db_connection()
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO courses (id, name, topics)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (id) DO UPDATE
                                SET name = %s, topics = %s
                            """, (course_id, course_name, course_topics, course_name, course_topics))
                            conn.commit()
                            st.success("✅ Curso salvo com sucesso!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar curso: {str(e)}")
                else:
                    st.error("❌ Preencha o ID e nome do curso!")
        
        st.markdown('<div class="course-container">', unsafe_allow_html=True)
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM courses ORDER BY name")
                courses = cur.fetchall()
                
                if courses:
                    for course in courses:
                        st.subheader(f"{course['name']} ({course['id']})")
                        st.write(f"**Tópicos:** {course['topics']}")
                        
                        if st.button("🗑️ Deletar", key=f"del_course_{course['id']}"):
                            try:
                                cur.execute("DELETE FROM courses WHERE id = %s", (course['id'],))
                                conn.commit()
                                st.success("✅ Curso deletado com sucesso!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao deletar curso: {str(e)}")
                        st.markdown("---")
                else:
                    st.info("ℹ️ Nenhum curso cadastrado.")
        except Exception as e:
            st.error(f"Erro ao carregar cursos: {str(e)}")
        st.markdown('</div>', unsafe_allow_html=True)
            
    elif menu == "Adicionar Aula":
        st.header("📝 Adicionar Nova Aula")
        st.markdown('<div class="course-container">', unsafe_allow_html=True)
        
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, name FROM courses ORDER BY name")
                courses = cur.fetchall()
                
                if courses:
                    course_options = {course['name']: course['id'] for course in courses}
                    selected_course = st.selectbox(
                        "Selecione o Curso",
                        options=list(course_options.keys())
                    )
                    
                    lesson_number = st.number_input("Número da Aula", min_value=1, value=1)
                    video_url = st.text_input("🎥 Link do YouTube")
                    pdf_url = st.text_input("📄 Link do PDF (Google Drive)")
                    
                    if st.button("💾 Salvar Aula"):
                        if video_url or pdf_url:
                            course_id = course_options[selected_course]
                            try:
                                cur.execute("""
                                    INSERT INTO lessons (course_id, lesson_number, video_url, pdf_url)
                                    VALUES (%s, %s, %s, %s)
                                    ON CONFLICT (course_id, lesson_number) 
                                    DO UPDATE SET video_url = %s, pdf_url = %s
                                """, (course_id, lesson_number, video_url, pdf_url, video_url, pdf_url))
                                conn.commit()
                                st.success("✅ Aula salva com sucesso!")
                                
                                st.subheader("Adicionar Quiz")
                                manage_quiz(course_id, lesson_number)
                                
                            except Exception as e:
                                st.error(f"Erro ao salvar aula: {str(e)}")
                        else:
                            st.warning("⚠️ Adicione pelo menos um vídeo ou PDF")
                else:
                    st.warning("⚠️ Cadastre um curso primeiro")
        except Exception as e:
            st.error(f"Erro ao carregar cursos: {str(e)}")
        st.markdown('</div>', unsafe_allow_html=True)
            
    elif menu == "Gerenciar Quiz":
        st.header("📝 Gerenciar Quiz")
        st.markdown('<div class="quiz-container">', unsafe_allow_html=True)
        
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.id, c.name, l.lesson_number
                    FROM courses c
                    JOIN lessons l ON c.id = l.course_id
                    ORDER BY c.name, l.lesson_number
                """)
                lessons = cur.fetchall()
                
                if lessons:
                    course_options = {
                        f"{lesson['name']} - Aula {lesson['lesson_number']}": 
                        (lesson['id'], lesson['lesson_number']) 
                        for lesson in lessons
                    }
                    selected_lesson = st.selectbox(
                        "Selecione a Aula",
                        options=list(course_options.keys())
                    )
                    
                    course_id, lesson_number = course_options[selected_lesson]
                    manage_quiz(course_id, lesson_number)
                else:
                    st.warning("⚠️ Adicione aulas primeiro")
        except Exception as e:
            st.error(f"Erro ao carregar aulas: {str(e)}")
        st.markdown('</div>', unsafe_allow_html=True)

def show_course_feedback_form(course_id):
    st.markdown('<div class="feedback-container">', unsafe_allow_html=True)
    feedback_text = st.text_area(
        "Sua avaliação do curso:",
        height=100,
        key=f"course_feedback_{course_id}"
    )
    
    if st.button("Enviar Avaliação", key=f"send_feedback_{course_id}"):
        if feedback_text.strip():
            if add_course_feedback(course_id, st.session_state.user_email, feedback_text):
                st.success("✅ Avaliação enviada com sucesso!")
                st.rerun()
        else:
            st.warning("⚠️ Por favor, escreva sua avaliação antes de enviar.")
    st.markdown('</div>', unsafe_allow_html=True)

def show_course_feedbacks(course_id):
    st.markdown('<div class="feedback-container">', unsafe_allow_html=True)
    feedbacks = get_course_feedback(course_id)
    if feedbacks:
        for feedback in feedbacks:
            st.markdown(f"""
            <div class="feedback-text">
                <strong>{feedback['user_email']}</strong>
                <br>
                {feedback['formatted_date']}
                <p>{feedback['feedback_text']}</p>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("ℹ️ Nenhuma avaliação disponível ainda.")
    st.markdown('</div>', unsafe_allow_html=True)

def show_student_dashboard():
    st.title("👨‍🎓 Área do Estudante")
    
    menu = st.sidebar.selectbox(
        "Menu",
        ["Meus Cursos", "Meu Progresso", "Avaliações", "Sair"]
    )
    
    manage_session(st.session_state.user_email, 'update')
    
    if menu == "Meus Cursos":
        st.header("📚 Meus Cursos")
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM courses 
                    WHERE id = ANY(%s)
                    ORDER BY name
                """, (st.session_state.permissions,))
                courses = cur.fetchall()
                
                if courses:
                    course_names = [course['name'] for course in courses]
                    selected_course = st.selectbox("Selecione um curso", course_names)
                    course = next(c for c in courses if c['name'] == selected_course)
                    
                    st.markdown('<div class="course-container">', unsafe_allow_html=True)
                    st.write(f"**Tópicos:** {course['topics']}")
                    
                    progress = get_student_progress(st.session_state.user_email, course['id'])
                    current_lesson = progress['current_lesson'] if progress else 1
                    completed_lessons = progress['completed_lessons'] if progress else []
                    
                    cur.execute("""
                        SELECT l.*, 
                               (SELECT COUNT(*) FROM quiz q 
                                WHERE q.course_id = l.course_id 
                                AND q.lesson_number = l.lesson_number) as quiz_count
                        FROM lessons l
                        WHERE l.course_id = %s 
                        ORDER BY l.lesson_number
                    """, (course['id'],))
                    lessons = cur.fetchall()
                    
                    if lessons:
                        total_lessons = len(lessons)
                        
                        if completed_lessons and len(completed_lessons) == total_lessons:
                            st.markdown("---")
                            st.subheader("📝 Avaliação do Curso")
                            show_course_feedback_form(course['id'])
                        
                        for lesson in lessons:
                            lesson_number = lesson['lesson_number']
                            is_available = verify_video_access(st.session_state.user_email, course['id'], lesson_number)
                            
                            st.markdown('<div class="lesson-container">', unsafe_allow_html=True)
                            col1, col2, col3 = st.columns([3, 1, 1])
                            with col1:
                                st.markdown(f'<p class="lesson-title">📖 Aula {lesson_number}</p>', unsafe_allow_html=True)
                            with col2:
                                if lesson_number in completed_lessons:
                                    st.success("✅ Concluída")
                                elif not is_available:
                                    st.warning("🔒 Bloqueada")
                                else:
                                    st.info("📝 Em andamento")
                            with col3:
                                total_likes, user_liked = get_lesson_likes(course['id'], lesson_number)
                                if st.button(
                                    f"{'❤️' if user_liked else '🤍'} {total_likes}",
                                    key=f"like_{course['id']}_{lesson_number}"
                                ):
                                    toggle_like(course['id'], lesson_number, st.session_state.user_email)
                                    st.rerun()
                            
                            if is_available:
                                if lesson['video_url']:
                                    video_id = extract_youtube_id(lesson['video_url'])
                                    if video_id:
                                        st.markdown('<div class="video-container">', unsafe_allow_html=True)
                                        st.video(f"https://youtu.be/{video_id}")
                                        log_video_view(st.session_state.user_email, course['id'], lesson_number)
                                        st.markdown('</div>', unsafe_allow_html=True)
                                
                                if lesson['pdf_url']:
                                    st.markdown(f"[📄 Material Complementar]({lesson['pdf_url']})")
                                
                                if lesson_number not in completed_lessons:
                                    show_quiz(course['id'], lesson_number)
                            else:
                                st.info("ℹ️ Complete a aula anterior para desbloquear esta aula.")
                            st.markdown('</div>', unsafe_allow_html=True)
                    else:
                        st.info("ℹ️ Ainda não há aulas disponíveis neste curso.")
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.warning("⚠️ Você ainda não tem acesso a nenhum curso")
        
        except Exception as e:
            st.error(f"Erro ao carregar cursos: {str(e)}")

    elif menu == "Meu Progresso":
        st.header("📊 Meu Progresso")
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.name, sp.current_lesson, sp.completed_lessons,
                           (SELECT COUNT(*) FROM lessons l WHERE l.course_id = c.id) as total_lessons
                    FROM courses c
                    JOIN student_progress sp ON c.id = sp.course_id
                    WHERE sp.email = %s
                """, (st.session_state.user_email,))
                progress = cur.fetchall()
                
                if progress:
                    for course in progress:
                        st.subheader(course['name'])
                        completed = len(course['completed_lessons']) if course['completed_lessons'] else 0
                        total = course['total_lessons']
                        
                        if total > 0:
                            progress_pct = (completed / total) * 100
                            st.progress(progress_pct / 100)
                            
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Aulas Completadas", f"{completed}/{total}")
                            with col2:
                                st.metric("Progresso", f"{progress_pct:.1f}%")
                            with col3:
                                st.metric("Aulas Restantes", f"{total - completed}")
                        else:
                            st.info("ℹ️ Nenhuma aula cadastrada neste curso ainda.")
                else:
                    st.info("ℹ️ Você ainda não iniciou nenhum curso.")
                    
        except Exception as e:
            st.error(f"Erro ao carregar progresso: {str(e)}")
    
    elif menu == "Avaliações":
        st.header("💬 Avaliações dos Cursos")
        try:
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.name as course_name,
                           f.*, u.email as student_email,
                           TO_CHAR(f.created_at, 'DD/MM/YYYY HH24:MI') as formatted_date
                    FROM lesson_feedback f
                    JOIN courses c ON f.course_id = c.id
                    JOIN users u ON f.email = u.email
                    WHERE f.lesson_number = 0
                        AND c.id = ANY(%s)
                    ORDER BY f.created_at DESC
                """, (st.session_state.permissions,))
                feedbacks = cur.fetchall()
                
                if feedbacks:
                    for feedback in feedbacks:
                        st.markdown(f"""
                        <div class="feedback-text">
                            <strong>{feedback['course_name']}</strong><br>
                            <em>{feedback['student_email']}</em> • {feedback['formatted_date']}<br>
                            {feedback['feedback_text']}
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("ℹ️ Nenhuma avaliação disponível ainda.")
        except Exception as e:
            st.error(f"Erro ao carregar avaliações: {str(e)}")
    
    elif menu == "Sair":
        manage_session(st.session_state.user_email, 'delete')
        st.session_state.logged_in = False
        st.rerun()

def main():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
    if 'permissions' not in st.session_state:
        st.session_state.permissions = None

    if not st.session_state.logged_in:
        st.markdown('<h1 class="big-font">🎓 Justificações Acadêmicas - Cursos Online</h1>', unsafe_allow_html=True)
        
        st.warning("""
        ⚠️ **Aviso de Segurança**
        - Seu acesso é individual e intransferível
        - Não compartilhe suas credenciais
        - Suas atividades são monitoradas
        - Múltiplos acessos simultâneos não são permitidos
        - O compartilhamento de credenciais pode resultar em bloqueio da conta
        """)
        
        st.markdown("""
        ### 📝 Acesso ao Sistema
        
        👨‍🎓 **Área do Estudante**
        - Email: `Digite seu e-mail`
        - Senha: `Digite sua senha`
        
        👨‍🏫 **Área do Professor**
        - Email: `Digite seu e-mail`
        - Senha: `Digite sua senha`
        """)

        col1, col2 = st.columns(2)
        with col1:
            email = st.text_input("📧 Email")
        with col2:
            senha = st.text_input("🔑 Senha", type="password")

        if st.button("🔐 Entrar"):
            if email and senha:
                success, permissions = verify_login(email, senha)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.user_email = email
                    st.session_state.permissions = permissions
                    st.success("✅ Login realizado com sucesso!")
                    st.rerun()
                else:
                    st.error("❌ Email ou senha incorretos")
            else:
                st.warning("⚠️ Por favor, preencha todos os campos")
    else:
        try:
            if 'admin' in st.session_state.permissions:
                show_admin_dashboard()
            else:
                show_student_dashboard()
        except Exception as e:
            st.error("Erro no sistema. Por favor, faça login novamente.")
            manage_session(st.session_state.user_email, 'delete')
            st.session_state.clear()
            st.rerun()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        st.error(f"Erro crítico no sistema: {str(e)}")
        if 'user_email' in st.session_state:
            manage_session(st.session_state.user_email, 'delete')
        st.session_state.clear()
        st.rerun()