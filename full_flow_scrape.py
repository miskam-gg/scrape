import time
import random
import logging
import os
import re
import sqlite3
import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


load_dotenv()
USERNAME = os.getenv("HH_USERNAME")
PASSWORD = os.getenv("HH_PASSWORD")
KEYWORDS = ["тестировщик", "автотестер", "manual", "qa", "aqa","автотестеровщик",]
COVER_LETTERS = os.getenv("COVER_LETTERS", "").split(";")


def random_delay(minimum=3, maximum=5):
    delay = random.uniform(minimum, maximum)
    logging.debug(f"Задержка {delay:.2f} секунд")
    time.sleep(delay)

def init_database(db_path="vacancies.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vacancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            employer TEXT,
            page_number INTEGER,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

def authorize_hh():
    logging.info("Запуск скрипта авторизации hh.ru")
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")
    options.set_capability("acceptInsecureCerts", True)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL", "driver": "ALL"})
    
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    driver.implicitly_wait(10)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    
    try:
        login_url = "https://hh.ru/account/login?backurl=%2Fapplicant%2Fresumes"
        logging.info("Открываем страницу логина: " + login_url)
        driver.get(login_url)
        random_delay()
        
        logging.info("Ожидание кнопки 'Войти'")
        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.supernova-button[data-qa="login"]'))
        )
        logging.debug("Найдена кнопка 'Войти', outerHTML: " + login_button.get_attribute('outerHTML'))
        login_button.click()
        logging.info("Клик по кнопке 'Войти'")
        random_delay()
        
        logging.info("Ожидание поля для ввода логина")
        login_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="login"]'))
        )
        login_input.send_keys(USERNAME)
        logging.info("Логин введён")
        random_delay()
        
        logging.info("Ожидание кнопки 'Войти с паролем'")
        expand_pass_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'span[data-qa="expand-login-by-password-text"]'))
        )
        expand_pass_btn.click()
        logging.info("Клик по кнопке 'Войти с паролем'")
        random_delay()
        
        logging.info("Ожидание поля для ввода пароля")
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-qa="login-input-password"]'))
        )
        password_input.send_keys(PASSWORD)
        logging.info("Пароль введён")
        random_delay()
        
        logging.info("Ожидание кнопки 'Войти в личный кабинет'")
        final_login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(., 'Войти') and contains(., 'личный')]"))
        )
        logging.debug("Найдена кнопка 'Войти в личный кабинет', outerHTML: " +
                      final_login_button.get_attribute('outerHTML'))
        final_login_button.click()
        logging.info("Клик по кнопке 'Войти в личный кабинет'")
        random_delay()
        
        time.sleep(5)
        current_url = driver.current_url
        logging.info("Текущий URL после входа: " + current_url)
        if "applicant" not in current_url:
            logging.info("URL не содержит 'applicant', выполняем принудительный переход на страницу резюме")
            forced_url = "https://hh.ru/applicant/resumes"
            driver.get(forced_url)
            time.sleep(5)
            logging.info("Новый URL: " + driver.current_url)
        else:
            logging.info("Редирект в личный кабинет выполнен успешно")
        
        logging.info("Авторизация завершена!")
        return driver
    except Exception as e:
        logging.exception("Ошибка при авторизации:")
        driver.quit()
        return None

def click_vacancies_button(driver):
    try:
        logging.info("Ожидание кнопки 'Подходящие вакансии'")
        vacancies_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//a[@data-qa='resume-recommendations__button_updateResume']"))
        )
        logging.debug("Найдена кнопка 'Подходящие вакансии', outerHTML: " + vacancies_button.get_attribute('outerHTML'))
        driver.execute_script("arguments[0].scrollIntoView(true);", vacancies_button)
        time.sleep(1)
        try:
            vacancies_button.click()
            logging.info("Клик по кнопке 'Подходящие вакансии' выполнен")
        except Exception as click_exception:
            logging.warning("Обычный клик не сработал, пробую принудительный клик через JavaScript")
            driver.execute_script("arguments[0].click();", vacancies_button)
            logging.info("Принудительный клик по кнопке 'Подходящие вакансии' выполнен")
        random_delay()
    except Exception as e:
        logging.exception("Ошибка при клике по кнопке 'Подходящие вакансии':")

def scrape_vacancies(driver, page_number, db_conn, main_window):
    try:
        logging.info(f"Начинаем сбор вакансий на странице {page_number}")
        vacancy_cards = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@data-qa, 'vacancy-serp__vacancy')]"))
        )
        logging.info(f"Найдено {len(vacancy_cards)} вакансий на странице {page_number}")
        cursor = db_conn.cursor()
        for index, card in enumerate(vacancy_cards, start=1):
            try:
                title_elem = card.find_element(By.XPATH, ".//span[@data-qa='serp-item__title-text']")
                employer_elem = card.find_element(By.XPATH, ".//span[@data-qa='vacancy-serp__vacancy-employer-text']")
                vacancy_title = title_elem.text.strip()
                employer_name = employer_elem.text.strip()
                
                if any(keyword.lower() in vacancy_title.lower() for keyword in KEYWORDS):
                    logging.info(f"!!! Вакансия {index} (стр. {page_number}): {vacancy_title} | Организация: {employer_name} [КЛЮЧЕВОЕ СЛОВО]")
                    cursor.execute("SELECT id FROM vacancies WHERE title=? AND employer=?", (vacancy_title, employer_name))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO vacancies (title, employer, page_number) VALUES (?, ?, ?)",
                                       (vacancy_title, employer_name, page_number))
                        logging.info(f"Вакансия {index} (стр. {page_number}) сохранена в БД")
                    else:
                        logging.info(f"Вакансия {index} (стр. {page_number}) уже присутствует в БД")
                    
                    driver.execute_script("arguments[0].scrollIntoView(true);", card)
                    time.sleep(1)
                    
                    vacancy_link = None
                    try:
                        vacancy_link = card.find_element(By.XPATH, ".//a[contains(@href, '/vacancy/')]").get_attribute("href")
                        logging.info(f"Ссылка вакансии: {vacancy_link}")
                    except Exception as link_exception:
                        logging.warning(f"Не удалось получить ссылку вакансии {index} (стр. {page_number}): {link_exception}")
                    
                    if vacancy_link:
                        driver.execute_script("window.open(arguments[0]);", vacancy_link)
                        time.sleep(1)
                        driver.switch_to.window(driver.window_handles[-1])
                        logging.info(f"Открыта новая вкладка для вакансии {index} (стр. {page_number})")
                        
                        try:
                            apply_button = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'magritte-button__label') and normalize-space(text())='Откликнуться']"))
                            )
                            logging.info("Кнопка 'Откликнуться' найдена на странице вакансии.")
                            apply_button.click()
                            logging.info("Нажата кнопка 'Откликнуться'.")
                        except Exception as e:
                            logging.info("Кнопка 'Откликнуться' не найдена на странице вакансии. Переходим к сценарию 3.")
                        
                        time.sleep(2)
                        scenario = None
                        cover_letter = random.choice(COVER_LETTERS)
                        try:
                            basic_textarea = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, "//textarea[@name='text']"))
                            )
                            scenario = 1
                        except:
                            pass
                        if scenario is None:
                            try:
                                modal_textarea = WebDriverWait(driver, 5).until(
                                    EC.presence_of_element_located((By.XPATH, "//textarea[@data-qa='vacancy-response-popup-form-letter-input']"))
                                )
                                scenario = 2
                            except:
                                pass
                        if scenario is None:
                            scenario = 3
                        
                        if scenario == 1:
                            logging.info("Сценарий 1 (базовый): Обнаружена простая форма для сопроводительного письма.")
                            basic_textarea.send_keys(cover_letter)
                            send_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'magritte-button__label') and normalize-space(text())='Отправить']"))
                            )
                            send_button.click()
                            logging.info("Сценарий 1: Нажата кнопка 'Отправить'.")
                        elif scenario == 2:
                            logging.info("Сценарий 2 (модальное окно): Обнаружена форма с обязательным сопроводительным письмом.")
                            try:
                                modal_dialog = WebDriverWait(driver, 15).until(
                                    EC.visibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
                                )
                                modal_textarea = modal_dialog.find_element(By.XPATH, ".//textarea[@data-qa='vacancy-response-popup-form-letter-input']")
                                modal_textarea.clear()
                                modal_textarea.send_keys(cover_letter)
                                logging.info("Введен текст сопроводительного письма в модальном окне.")
                                # Используем XPath для поиска кнопки внутри модального окна
                                modal_apply_button = modal_dialog.find_element(By.XPATH, ".//button[.//span[normalize-space(text())='Откликнуться']]")
                                WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable((By.XPATH, ".//button[.//span[normalize-space(text())='Откликнуться']]"))
                                )
                                driver.execute_script("arguments[0].click();", modal_apply_button)
                                logging.info("Сценарий 2: Принудительно нажата кнопка 'Откликнуться' в модальном окне через JavaScript.")
                            except Exception as modal_e:
                                logging.error("Сценарий 2: Ошибка при обработке модального окна: " + str(modal_e))
                        elif scenario == 3:
                            logging.info("Сценарий 3: Редирект или отсутствие формы – никаких дополнительных действий не производится.")
                        
                        time.sleep(3)
                        driver.close()
                        logging.info(f"Закрыта вкладка для вакансии {index} (стр. {page_number})")
                        driver.switch_to.window(main_window)
                    else:
                        logging.info(f"Ссылка вакансии {index} (стр. {page_number}) не найдена, пропускаем открытие в новой вкладке")
                else:
                    logging.info(f"Вакансия {index} (стр. {page_number}): {vacancy_title} | Организация: {employer_name}")
            except Exception as inner_e:
                logging.warning(f"Ошибка при обработке вакансии {index} на странице {page_number}: {inner_e}")
        db_conn.commit()
    except Exception as e:
        logging.exception("Ошибка при сборе данных по вакансиям:")

def get_total_pages(driver):
    try:
        pages = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.XPATH, "//ul[contains(@class, 'magritte-number-pages-container')]//a[@data-qa='pager-page']"))
        )
        page_numbers = []
        for p in pages:
            try:
                page_numbers.append(int(p.text.strip()))
            except:
                continue
        max_page = max(page_numbers) if page_numbers else 1
        logging.info(f"Обнаружено {max_page} страниц вакансий")
        return max_page
    except Exception as e:
        logging.exception("Ошибка при получении количества страниц:")
        return 1

def go_to_page(driver, page_number):
    try:
        logging.info(f"Переход на страницу вакансий {page_number}")
        current_url = driver.current_url
        if "page=" in current_url:
            new_url = re.sub(r"page=\d+", f"page={page_number-1}", current_url)
        else:
            new_url = current_url + f"&page={page_number-1}"
        logging.info("Новый URL для пагинации: " + new_url)
        driver.get(new_url)
        time.sleep(5)
    except Exception as e:
        logging.exception(f"Ошибка при переходе на страницу {page_number}:")

if __name__ == "__main__":
    db_conn = init_database()
    driver = authorize_hh()
    if driver:
        main_window = driver.current_window_handle
        click_vacancies_button(driver)
        time.sleep(3)
        total_pages = get_total_pages(driver)
        for page in range(1, total_pages + 1):
            go_to_page(driver, page)
            scrape_vacancies(driver, page, db_conn, main_window)
            time.sleep(5)
        logging.info("Обход всех страниц завершён. Теперь обновляем первую страницу каждые 5 минут и ищем новые вакансии.")
        while True:
            go_to_page(driver, 1)
            scrape_vacancies(driver, 1, db_conn, main_window)
            logging.info("Ожидание 5 минут до следующего обновления первой страницы...")
            time.sleep(300)
