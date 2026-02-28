import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router';
import {
  Home,
  LayoutDashboard,
  Users,
  Settings,
  Info,
  Moon,
  Sun,
  ChevronRight,
  Tv,
  Film,
} from 'lucide-react';
import { Button } from '~/components/ui/button';
import {
  Sidebar,
  SidebarProvider,
  SidebarContent,
  SidebarHeader,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubItem,
  SidebarMenuSubButton,
  SidebarFooter,
  SidebarTrigger,
  SidebarRail,
  useSidebar,
} from '~/components/ui/sidebar';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { useTheme } from '~/hooks/use-theme';
import { checkAuth } from '~/lib/auth-helpers';
import { Input } from '~/components/ui/input';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '~/components/ui/input-group';
import useAuthStore from '~/store/auth';
import useSettingsStore from '~/store/settings';
import useChannelsStore from '~/store/channels';
import { Copy } from 'lucide-react';
import FloatingVideo from './FloatingVideo';
import { WebsocketProvider } from '~/hooks/use-websocket';

type NavItem = {
  title: string;
  icon: any;
  url?: string;
  items?: { title: string; url: string }[];
};

const navItems: NavItem[] = [
  { title: 'Home', icon: Home, url: '/' },
  { title: 'Dashboard', icon: LayoutDashboard, url: '/dashboard' },
  {
    title: 'Content',
    icon: Tv,
    items: [
      { title: 'Channels', url: '/channels' },
      { title: 'VOD', url: '/vod' },
      { title: 'Series', url: '/series' },
      { title: 'EPG', url: '/epg' },
    ],
  },
  {
    title: 'Media',
    icon: Film,
    items: [
      { title: 'Movies', url: '/movies' },
      { title: 'TV Shows', url: '/tv-shows' },
      { title: 'Live TV', url: '/live-tv' },
    ],
  },
  { title: 'Users', icon: Users, url: '/users' },
  { title: 'Settings', icon: Settings, url: '/settings' },
  { title: 'About', icon: Info, url: '/about' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const [isChecking, setIsChecking] = useState(true);

  const initData = useAuthStore((s) => s.initData);

  useEffect(() => {
    const checkAuthentication = async () => {
      const authenticated = await checkAuth();
      if (!authenticated) {
        navigate('/login', { replace: true });
      } else {
        await initData();
        setIsChecking(false);
      }
    };

    checkAuthentication();
  }, [navigate]);

  // Show loading state while checking auth
  if (isChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent"></div>
          <p className="mt-2 text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <WebsocketProvider>
      <SidebarProvider
        style={
          {
            '--sidebar-width': '18rem',
            '--sidebar-width-icon': '3.3rem',
          } as React.CSSProperties
        }
      >
        <AppLayoutContent />
      </SidebarProvider>
    </WebsocketProvider>
  );
}

function AppLayoutContent() {
  const { theme, toggleTheme } = useTheme();
  const { toggleSidebar, state } = useSidebar();
  const isCollapsed = state === 'collapsed';
  const location = useLocation();

  const channelIds = useChannelsStore((s) => s.channelIds);
  const environment = useSettingsStore((s) => s.environment);
  const appVersion = useSettingsStore((s) => s.version);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const authUser = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="flex min-h-screen w-full">
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center justify-center px-2 py-2 group-data-[collapsible=icon]:px-0">
            <button
              onClick={toggleSidebar}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity w-full group-data-[collapsible=icon]:w-auto"
              aria-label="Toggle sidebar"
              title="Toggle sidebar"
            >
              <img
                src="/logo.png"
                alt="Dispatcharr"
                className="h-8 w-8 shrink-0"
              />
              <div className="flex flex-1 flex-col group-data-[collapsible=icon]:hidden">
                <span className="text-sm font-semibold">Dispatcharr</span>
              </div>
            </button>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {navItems.map((item) => {
                  // If item has sub-items, render as collapsible or dropdown
                  if (item.items) {
                    const hasActiveChild = item.items.some(
                      (subItem) => location.pathname === subItem.url
                    );

                    // When collapsed, use DropdownMenu for sub-items
                    if (isCollapsed) {
                      return (
                        <SidebarMenuItem key={item.title}>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <SidebarMenuButton
                                tooltip={item.title}
                                className={
                                  hasActiveChild ? '!bg-emerald-500/10' : ''
                                }
                              >
                                <item.icon className="h-4 w-4" />
                                <span>{item.title}</span>
                              </SidebarMenuButton>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              side="right"
                              align="start"
                              className="w-48"
                            >
                              {item.items.map((subItem) => {
                                const isActive =
                                  location.pathname === subItem.url;
                                return (
                                  <DropdownMenuItem key={subItem.title} asChild>
                                    <Link
                                      to={subItem.url}
                                      className={
                                        isActive
                                          ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400'
                                          : ''
                                      }
                                    >
                                      {subItem.title}
                                    </Link>
                                  </DropdownMenuItem>
                                );
                              })}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </SidebarMenuItem>
                      );
                    }

                    // When expanded, use Collapsible for sub-items
                    return (
                      <Collapsible
                        key={item.title}
                        defaultOpen={hasActiveChild}
                        className="group/collapsible"
                      >
                        <SidebarMenuItem>
                          <CollapsibleTrigger asChild>
                            <SidebarMenuButton
                              tooltip={item.title}
                              className={
                                hasActiveChild ? '!bg-emerald-500/10' : ''
                              }
                            >
                              <item.icon className="h-4 w-4" />
                              <span>{item.title}</span>
                              <ChevronRight className="ml-auto h-4 w-4 transition-transform group-data-[state=open]/collapsible:rotate-90" />
                            </SidebarMenuButton>
                          </CollapsibleTrigger>
                          <CollapsibleContent>
                            <SidebarMenuSub>
                              {item.items.map((subItem) => {
                                const isActive =
                                  location.pathname === subItem.url;
                                return (
                                  <SidebarMenuSubItem key={subItem.title}>
                                    <SidebarMenuSubButton
                                      asChild
                                      isActive={isActive}
                                    >
                                      <Link to={subItem.url}>
                                        <span>{subItem.title}</span>
                                      </Link>
                                    </SidebarMenuSubButton>
                                  </SidebarMenuSubItem>
                                );
                              })}
                            </SidebarMenuSub>
                          </CollapsibleContent>
                        </SidebarMenuItem>
                      </Collapsible>
                    );
                  }

                  // Regular menu item without sub-items
                  const isActive = location.pathname === item.url;
                  return (
                    <SidebarMenuItem key={item.title}>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive}
                        tooltip={item.title}
                        className={
                          isActive
                            ? '!bg-emerald-500/20 !border-1 !border-emerald-500 hover:!bg-emerald-500/30'
                            : ''
                        }
                      >
                        <Link to={item.url!}>
                          <item.icon className="h-4 w-4" />
                          <span>{item.title}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter>
          {!isCollapsed && (
            <InputGroup>
              <InputGroupInput
                id="input-group-url"
                placeholder={environment.public_ip}
              />
              <InputGroupAddon align="inline-end">
                <Button variant="ghost">
                  <Copy />
                </Button>
              </InputGroupAddon>
              <InputGroupAddon>
                {environment.country_code && (
                  <img
                    src={`https://flagcdn.com/16x12/${environment.country_code.toLowerCase()}.png`}
                    alt={environment.country_name || environment.country_code}
                    title={environment.country_name || environment.country_code}
                  />
                )}
              </InputGroupAddon>
            </InputGroup>
          )}

          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {theme === 'light' ? (
              <Moon className="h-5 w-5" />
            ) : (
              <Sun className="h-5 w-5" />
            )}
          </Button>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>

      <div className="flex-1 flex flex-col">
        {/* Main Content */}
        <main className="flex-1 bg-background">
          <Outlet />
        </main>
      </div>

      <FloatingVideo />
    </div>
  );
}
