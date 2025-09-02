from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import requests
from typing import List

from anubis_core.features.blog.models import CorePost
from anubis_core.features.blog.ports import IPostAdapter
from anubis_core.ports.cdn_manager import ICdnManagerPort

SCOPES = ["https://www.googleapis.com/auth/blogger"]

class BloggerPostAdapter(IPostAdapter):
    def __init__(self, id_blogger: str, client_secret_file: str, cdn_post_adapter: ICdnManagerPort ):
        self.id_blogger = id_blogger
        self.client_secret_file = client_secret_file        
        self.creds = None
        self.blogger_service = None
        self.cdn_manage = cdn_post_adapter

        
    def _bind(self):
        if not self.creds:
            try:
                self.creds = Credentials.from_authorized_user_file(self.client_secret_file)
            except Exception as e:
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_file, SCOPES)
                self.creds = flow.run_local_server(port=0)
                with open(self.client_secret_file, 'w') as token:
                    token.write(self.creds.to_json())
            
            self.blogger_service = build('blogger', 'v3', credentials=self.creds)

    def pull_post(self, post_id: str) -> CorePost:
        """Obtiene un post de Blogger por su ID."""
        self._bind()
        post_response = self.blogger_service.posts().get(blogId=self.id_blogger, postId=post_id).execute()

        post = CorePost(
            id = post_response['id'],
            title= post_response['title'],
            content= post_response['content'],
            tags= post_response['content']  if 'labels' in post_response.keys() else [],
            url=post_response['url'],
            update_date=post_response['updated'],
            publish_date=post_response['published'],
        )
        
        return post        

    def push_post(self, post: CorePost) -> CorePost:
        """Crea o actualiza un post en Blogger."""
        self._bind()

        filename = f"{self.cdn_manage.convert_filename(post.title)}.jpg" 
        image_public_html=""

        if self.cdn_manage.check_filename(filename):
            image_public_html = self.cdn_manage.send_file(filename,post.images_base64[0],f"Send form blogger Blog Post Adapter - {filename}")        
        
        img_html = f'<img src="{image_public_html}" alt="Imagen" style="width:100%">'
        
        data = {
            "title": post.title,
            "content": f"{img_html}<br />{post.content}",
            "status": "LIVE" if post.status == "publish" else "DRAFT",
            'images': [{'url': image_public_html}]  # Establecer imagen principal
        }
        
        if post.id:  # Si tiene ID, actualizar post existente
            post_response = self.blogger_service.posts().update(blogId=self.id_blogger, postId=post.id, body=data).execute()            
        else:  # Si no tiene ID, crear nuevo post            
            

            post_response = self.blogger_service.posts().insert(blogId=self.id_blogger, body=data).execute()
            post.id = post_response["id"]
        return post
        
        
    def search_posts(self, search_text: str) -> List[CorePost]:
        """Busca posts en Blogger que coincidan con el texto dado."""
        self._bind()
        
        try:
            posts_out = []
            next_page_token = None

            while True:
                # Obtener posts con paginación
                request = self.blogger_service.posts().list(
                    blogId=self.id_blogger, 
                    maxResults=100, 
                    pageToken=next_page_token  # Siguiente página
                )
                posts = request.execute()
                posts_list = posts.get('items', [])

                # Filtrar los posts por título o contenido
                for post in posts_list:
                    if search_text.lower() in post.get('title', '').lower() or search_text.lower() in post.get('content', '').lower():
                        posts_out.append(self._parse_post_json(post))

                # Revisar si hay más páginas
                next_page_token = posts.get('nextPageToken')
                if not next_page_token:
                    break  # Salir si no hay más páginas

            return posts_out
        except Exception as e:
            print(f"Error al buscar posts: {e}")
            return []



    def _parse_post_json(self, json) -> CorePost:
        return  CorePost(
            id = json['id'] if 'id' in json.keys() else None,
            title= json['title'],
            content= json['content'],
            tags= json['labels']  if 'labels' in json.keys() else [],
            url=json['url'] if 'url' in json.keys() else None,
            update_date=json['updated']if 'updated' in json.keys() else None,
            publish_date=json['published']if 'published' in json.keys() else None,
        )
