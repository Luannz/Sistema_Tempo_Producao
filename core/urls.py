# ==================== URLS.PY ====================
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('inicio/', views.inicio, name='inicio'),
    path('painel/administrador/', views.inicio_administrador, name='inicio_administrador'),
    path('painel/supervisor/', views.inicio_supervisor, name='inicio_supervisor'),
    path('registrar/', views.registrar_view, name='registrar'),

    # ================= SETORES E OPERADORES ==================
    path('setores/', views.listar_setores, name='listar_setores'),
    path('operadores/', views.listar_operadores, name='listar_operadores'),
    path('operadores/<int:operador_id>/status/',views.alterar_status_operador,name='alterar_status_operador'),
    path('operadores/<int:operador_id>/excluir/',views.excluir_operador,name='excluir_operador'),

    # ==================== MODELOS E PECAS ====================
    path('modelos/cadastro/', views.cadastro_modelo, name='cadastro_modelo'),
    path('modelos/<int:modelo_id>/alterar_status/', views.alterar_status_modelo, name='alterar_status_modelo'),
    path('modelos/<int:modelo_id>/excluir/', views.excluir_modelo, name='excluir_modelo'),
    
    path('pecas/cadastro/', views.cadastro_peca, name='cadastro_peca'),
    path('pecas/<int:peca_id>/status/', views.alterar_status_peca, name='alterar_status_peca'),
    path('pecas/<int:peca_id>/excluir/', views.excluir_peca, name='excluir_peca'),

    # ==================== FICHAS ====================
    path('fichas/nova/', views.criar_ficha, name='criar_ficha'),
    path('fichas/<int:ficha_id>/', views.detalhe_ficha, name='detalhe_ficha'),
    path('fichas/<int:ficha_id>/visualizar/', views.visualizar_ficha, name='visualizar_ficha'),
    path('fichas/<int:ficha_id>/excluir/',views.excluir_ficha,name='excluir_ficha'),
    
    path('ficha/item/<int:item_id>/remover/', views.remover_item_ficha, name='remover_item_ficha'),
    path('ficha/peca/<int:peca_habilitada_id>/remover/', views.remover_peca_ficha, name='remover_peca_ficha'),

    # ==================== RELATÓRIOS ========================
    path('relatorios/operadores/', views.relatorios_producao, name='relatorios_producao'),
    
    # ==================== HISTORICO ====================
    path('historico/fichas/', views.historico_fichas, name='historico_fichas'),
    path('historico/fichas/<int:usuario_id>/', views.historico_ficha_usuario, name='historico_fichas_usuario'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
