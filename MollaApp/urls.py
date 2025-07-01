from django.contrib import admin
from django.urls import path
from MollaApp import views
from django.contrib.auth import views as auth_views


urlpatterns = [
	path("", views.home, name='home'),
	path("about", views.about, name='about'),
	path("page_404", views.page_404, name='page_404'),
	path("blog", views.blog, name='blog'),
	path("cart", views.cart, name='cart'),
	path("products/category", views.category_product, name='category'),
	path("checkout/", views.checkout, name='checkout'),
	path("coming_soon", views.coming_soon, name='coming_soon'),
	path("contact", views.contact, name='contact'),
	path("dashboard", views.dashboard, name='dashboard'),
	path("faq", views.faq, name='faq'),
	path("login", views.login, name='login'),
	path("signup", views.signup, name='signup'),
	path("product/<int:value>/", views.product, name='product'),
	path("products/pet/<str:value>/", views.pets_product, name='pets_product'),
	path("single", views.single, name='single'),
	path("wishlist", views.wishlist, name='wishlist'),
	path("quickView", views.quickView, name='quickView'),
    path("delete_product/",views.delete_product, name='delete_product'),
    path('logout/', views.logout, name='logout'),
    path('update_profile/', views.update_profile, name='update_profile'),
    path('update_quantity/', views.update_quantity, name='update_quantity'),
    path('filtered-products/', views.filtered_products, name='filtered_products'),
    path('order-placed/', views.order_placed, name='order_placed'),
    path('save_product/', views.save_product, name='save_product'),
    path('products/category/<str:value>/', views.product_by_category, name='product_by_category'),
    path('search/', views.search_products, name='search_products'),
    path('subscribe/', views.subscribe, name='subscribe'),
    path('checkout_view/', views.checkout_view, name='checkout_view'),

]